"""Build gate: a fix that clears the scanner but breaks the build or the tests must NOT be verified."""
import pytest
from app import build
from tests.test_pipeline import DEV, REV, env, scan  # noqa: F401  (fixture reuse)


def _patch_maven(monkeypatch, patched_compile=True, patched_tests=True, baseline_tests=True):
    build._baseline_cache.clear()
    calls = {"n": 0}

    def fake(root, *goals, timeout=900):
        calls["n"] += 1
        baseline_phase = calls["n"] <= (2 if baseline_tests else 1) + 0  # compile(+test) of the baseline
        if baseline_phase:
            return True, ""
        if "compile" in goals:
            return patched_compile, "COMPILATION ERROR"
        return patched_tests, "Tests run: 3, Failures: 1"

    monkeypatch.setattr(build, "run_mvn", fake)
    monkeypatch.setattr(build, "find_mvn", lambda: "mvn")
    monkeypatch.setattr(build, "applicable", lambda root, fp: fp.endswith(".java"))


def _attempts(c):
    f = next(x for x in c.get("/findings", headers=DEV).json() if x["cwe_id"] == "CWE-798")
    return f["id"], [a["verification"] for a in c.get(f"/findings/{f['id']}", headers=DEV).json()["attempts"]]


def test_patch_that_breaks_compile_is_rejected(env, monkeypatch):
    c, repo, _ = env
    _patch_maven(monkeypatch, patched_compile=False)
    scan(c, repo)
    fid, att = _attempts(c)
    assert att[0] == "build_failed" and "resolved" not in att
    assert len(att) == 3  # REQ-008: exactly three automated attempts, then escalation
    actions = [e["action"] for e in c.get(f"/audit/{fid}", headers=DEV).json()]
    assert "escalated" in actions
    assert c.post(f"/findings/{fid}/decision", json={"decision": "approve"}, headers=REV).status_code == 409


def test_patch_that_breaks_tests_is_rejected(env, monkeypatch):
    c, repo, _ = env
    _patch_maven(monkeypatch, patched_compile=True, patched_tests=False)
    scan(c, repo)
    _, att = _attempts(c)
    assert att[0] == "build_failed"


def test_green_build_is_verified(env, monkeypatch):
    c, repo, _ = env
    _patch_maven(monkeypatch)
    scan(c, repo)
    _, att = _attempts(c)
    assert att == ["resolved"]


def test_broken_baseline_does_not_block_fixes(monkeypatch):
    build._baseline_cache.clear()
    monkeypatch.setattr(build, "run_mvn", lambda *a, **k: (False, "baseline broken"))
    base = build.baseline.__wrapped__ if hasattr(build.baseline, "__wrapped__") else None
    info = build.baseline(__import__("pathlib").Path("."), "sha-x")
    assert info["compiles"] is False
    assert build.gate(__import__("pathlib").Path("."), info)["ok"] is True
