"""Build & test verification gate (Module 4 extension).

A fix is only 'resolved' if (1) static analysis no longer reports it, (2) the project still compiles, and
(3) if the baseline test suite was runnable, it still passes. Without (2)/(3) a fix that deletes the vulnerable
line, or breaks the build, would pass verification (the circularity of re-scanning with the same scanner).
The gate is differential: it compares against the unmodified base branch so a repo that is already broken
(e.g. stale tests) is reported honestly instead of blocking every fix.
"""
import os
import shutil
import subprocess
from pathlib import Path

JAVA_EXT = (".java",)
_baseline_cache: dict[str, dict] = {}


def find_mvn() -> str | None:
    exe = shutil.which("mvn") or shutil.which("mvn.cmd")
    if exe:
        return exe
    home = os.getenv("MAVEN_HOME")
    if home:
        for name in ("mvn.cmd", "mvn"):
            p = Path(home) / "bin" / name
            if p.exists():
                return str(p)
    return None


def applicable(root: Path, file_path: str) -> bool:
    """Gate applies to Maven projects and to changes in compiled code (not .properties)."""
    return (root / "pom.xml").exists() and file_path.endswith(JAVA_EXT) and find_mvn() is not None


def run_mvn(root: Path, *goals: str, timeout: int = 900) -> tuple[bool, str]:
    exe = find_mvn()
    try:
        p = subprocess.run([exe, "-B", "-q", "-o", *goals], cwd=root, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ})
        if p.returncode and "offline" in (p.stdout + p.stderr).lower():  # deps not cached yet: retry online
            p = subprocess.run([exe, "-B", "-q", *goals], cwd=root, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "maven timed out"
    out = (p.stdout + p.stderr).strip().splitlines()
    errs = [ln for ln in out if ".java" in ln and "ERROR" in ln]
    tail = "\n".join(errs[:2] if errs else out[-6:])  # the compiler's own error lines, not Maven boilerplate
    return p.returncode == 0, tail


def baseline(root: Path, sha: str) -> dict:
    """Compile/test status of the unmodified base commit, cached per commit. `root` must be a clean checkout."""
    if sha in _baseline_cache:
        return _baseline_cache[sha]
    compiled, _ = run_mvn(root, "compile")
    tests_ok, tail = run_mvn(root, "test") if compiled else (False, "")
    res = {"compiles": compiled, "tests_runnable": tests_ok, "note": "" if tests_ok else "baseline tests do not run/pass"}
    _baseline_cache[sha] = res
    return res


def gate(root: Path, base: dict) -> dict:
    """Run on a patched checkout. Returns {ok, detail}."""
    if not base["compiles"]:
        return {"ok": True, "detail": "WARNING: baseline does not compile, so the build gate could not verify this fix"}
    ok, tail = run_mvn(root, "compile")
    if not ok:
        return {"ok": False, "detail": "patched code no longer compiles: " + tail.replace("\n", " ")[:300]}
    if base["tests_runnable"]:
        ok, tail = run_mvn(root, "test")
        if not ok:
            return {"ok": False, "detail": "existing tests fail after the patch: " + tail.replace("\n", " ")[:300]}
        return {"ok": True, "detail": "compiles and existing tests pass"}
    return {"ok": True, "detail": "compiles (baseline tests not runnable, so regression tests skipped)"}
