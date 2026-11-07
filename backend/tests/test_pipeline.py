import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config, db as dbmod, main
from app.models import AuditLogEntry, Base

SAMPLE = Path(__file__).resolve().parents[2] / "sample_target" / "african-arts-craft-api"
DEV, REV = {"X-User-Id": "1"}, {"X-User-Id": "2"}


def sh(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    repo = tmp_path / "target"
    shutil.copytree(SAMPLE, repo)
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    monkeypatch.setattr(config, "ALLOWED_ROOTS", [tmp_path.resolve()])
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    dbmod.init_db(eng)
    Session = sessionmaker(bind=eng, expire_on_commit=False)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    main.app.dependency_overrides[dbmod.get_db] = override
    main.app.dependency_overrides[main.get_db] = override
    yield TestClient(main.app), repo, Session
    main.app.dependency_overrides.clear()


def scan(c, repo):
    r = c.post("/scans", json={"repo_path": str(repo)}, headers=DEV)
    assert r.status_code == 200, r.text
    return r.json()


def test_detects_all_four_classes(env):
    c, repo, _ = env
    assert scan(c, repo)["findings"] == 5
    cwes = sorted(f["cwe_id"] for f in c.get("/findings", headers=DEV).json())
    assert cwes == ["CWE-798", "CWE-862", "CWE-89", "CWE-916", "CWE-916"]


def test_fixes_verified_on_branch_and_target_untouched(env):
    c, repo, _ = env
    scan(c, repo)
    before = sh(repo, "rev-parse", "main")
    fs = c.get("/findings?status=pending", headers=DEV).json()
    assert len(fs) == 5 and all(f["verification"] == "resolved" for f in fs)
    assert sh(repo, "rev-parse", "main") == before  # REQ-005/NFR-001: nothing merged without approval


def test_secret_never_stored_or_shown(env):
    c, repo, Session = env
    scan(c, repo)
    cred = next(f for f in c.get("/findings", headers=DEV).json() if f["cwe_id"] == "CWE-798")
    detail = c.get(f"/findings/{cred['id']}", headers=DEV).text
    assert "P@ssw0rd123" not in detail
    with Session() as s:
        assert all("P@ssw0rd123" not in (e.detail or "") for e in s.query(AuditLogEntry))


def test_approve_merges_and_audit_trail(env):
    c, repo, _ = env
    scan(c, repo)
    fid = next(f["id"] for f in c.get("/findings", headers=DEV).json() if f["cwe_id"] == "CWE-798")
    assert c.post(f"/findings/{fid}/decision", json={"decision": "approve"}, headers=DEV).status_code == 403
    r = c.post(f"/findings/{fid}/decision", json={"decision": "approve"}, headers=REV)
    assert r.status_code == 200 and r.json()["status"] == "merged"
    assert 'System.getenv("DB_PASSWORD")' in (repo / "src/main/java/za/co/artscraft/config/AuthConfig.java").read_text()
    actions = [e["action"] for e in c.get(f"/audit/{fid}", headers=DEV).json()]
    assert actions[0] == "scan_started" and actions[-1] == "merged"
    assert {"finding_recorded", "explanation_generated", "fix_attempt", "reviewed"} <= set(actions)
    assert c.get("/audit/verify", headers=DEV).json()["valid"] is True


def test_reject_does_not_merge_and_request_changes_retriages(env):
    c, repo, _ = env
    scan(c, repo)
    before = sh(repo, "rev-parse", "main")
    f = c.get("/findings", headers=DEV).json()
    r = c.post(f"/findings/{f[0]['id']}/decision", json={"decision": "reject"}, headers=REV)
    assert r.json()["status"] == "rejected" and sh(repo, "rev-parse", "main") == before
    r = c.post(f"/findings/{f[1]['id']}/decision", json={"decision": "request_changes", "feedback": "use a vault"}, headers=REV)
    assert r.status_code == 200 and len(r.json()["attempts"]) >= 2 and r.json()["status"] == "awaiting_review"
    assert c.post(f"/findings/{f[0]['id']}/decision", json={"decision": "approve"}, headers=REV).status_code == 409


def test_audit_log_is_immutable_and_tamper_evident(env):
    c, repo, Session = env
    scan(c, repo)
    with Session() as s:
        e = s.query(AuditLogEntry).first()
        e.detail = "tampered"
        with pytest.raises(PermissionError):
            s.flush()
        s.rollback()
        s.execute(AuditLogEntry.__table__.update().where(AuditLogEntry.log_id == 1).values(detail="x"))  # raw SQL bypass
        s.commit()
    assert c.get("/audit/verify", headers=DEV).json() == {"valid": False, "broken_at": 1, "entries": c.get("/audit/verify", headers=DEV).json()["entries"]}


def test_scope_and_path_traversal_rejected(env, tmp_path):
    c, repo, _ = env
    outside = tmp_path.parent / "elsewhere"
    outside.mkdir(exist_ok=True)
    assert c.post("/scans", json={"repo_path": str(outside)}, headers=DEV).status_code == 403
    from app.staging import StagingError, safe_path
    with pytest.raises(StagingError):
        safe_path(repo, "../../etc/passwd")


def test_findings_grouped_by_root_cause(env):
    c, repo, _ = env
    scan(c, repo)
    groups = c.get("/findings/groups", headers=DEV).json()
    assert sum(g["count"] for g in groups) == 5
    assert {g["rule_id"] for g in groups} >= {"lg-hardcoded-credential", "lg-sql-injection"}
    assert all(len(g["locations"]) == g["count"] for g in groups)
