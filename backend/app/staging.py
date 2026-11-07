"""Remediation Staging & Verification (Module 4).

Applies a patch on an isolated branch (via a throw-away git worktree) and re-scans it.
This module has NO merge function: the only merge lives in review.py and needs an approving Review (NFR-001).
"""
import difflib
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import build
from .scanner import line_hash, redact, run_static_analysis


class StagingError(Exception):
    pass


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode:
        raise StagingError(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout.strip()


def safe_path(root: Path, rel: str) -> Path:
    p = (root / rel).resolve()
    if root.resolve() not in p.parents:
        raise StagingError(f"path escapes repository: {rel}")
    return p


def locate_line(lines: list[str], lh: str, near: int) -> int | None:
    hits = [i for i, l in enumerate(lines) if line_hash(l) == lh]
    return min(hits, key=lambda i: abs(i - (near - 1))) if hits else None


def read_source(repo: Path, rel: str, lh: str, near: int, base: str):
    """Return (line, context_lines) for the flagged line as it exists on the base branch."""
    text = git(repo, "show", f"{base}:{rel}")
    lines = text.splitlines()
    idx = locate_line(lines, lh, near)
    if idx is None:
        raise StagingError("flagged line no longer present on base branch")
    return lines[idx], lines[max(0, idx - 5): idx + 6]


def display_diff(rel: str, old: str, new_text: str) -> str:
    return "".join(difflib.unified_diff([redact(old) + "\n"], [redact(l) + "\n" for l in new_text.splitlines()],
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}", n=0))


def apply_and_rescan(repo: Path, base: str, branch: str, finding: dict, new_text: str | None) -> dict:
    """finding: dict(file_path, line_number, line_hash, rule_id, cwe_id). Returns a verification result."""
    if not new_text:
        return {"result": "no_patch", "branch": None, "diff": "", "detail": "agent could not produce a safe fix"}
    work = Path(tempfile.mkdtemp(prefix="lg-stage-"))
    shutil.rmtree(work)
    try:
        git(repo, "worktree", "add", "-q", "-B", branch, str(work), base)
        target = safe_path(work, finding["file_path"])
        lines = target.read_text(encoding="utf-8").splitlines()
        idx = locate_line(lines, finding["line_hash"], finding["line_number"])
        if idx is None:
            raise StagingError("flagged line not found in worktree")
        old = lines[idx]
        indent = old[: len(old) - len(old.lstrip())]
        new_lines = [(indent + l.lstrip()) if not l[:1].isspace() else l for l in new_text.splitlines()]
        gate_on = build.applicable(work, finding["file_path"])
        base_info = build.baseline(work, git(work, "rev-parse", "HEAD")) if gate_on else None
        # Every line of the same rule+file before/after: a fix must reduce the count and add no new finding.
        before = [f for f in run_static_analysis(work)]
        lines[idx: idx + 1] = new_lines
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        after = run_static_analysis(work)
        same = lambda fs: sum(1 for f in fs if f["rule_id"] == finding["rule_id"] and f["file_path"] == finding["file_path"])
        resolved = same(after) < same(before) and len(after) < len(before)
        detail = "re-scan confirmed the finding is gone" if resolved else "re-scan still reports the issue"
        result = "resolved" if resolved else "not_resolved"
        if resolved and gate_on:
            g = build.gate(work, base_info)
            detail += "; build gate: " + g["detail"]
            if not g["ok"]:
                resolved, result = False, "build_failed"
        elif resolved:
            detail += "; build gate: not applicable (non-Java file or no Maven project)"
        if resolved:
            git(work, "add", "--", finding["file_path"])
            git(work, "-c", "user.name=LegacyGuard", "-c", "user.email=legacyguard@local", "commit", "-q", "-m",
                f"LegacyGuard: fix {finding['cwe_id']} in {finding['file_path']} (staged, awaiting human review)")
        return {"result": result, "branch": branch if resolved else None,
                "diff": display_diff(finding["file_path"], old, "\n".join(new_lines)), "detail": detail}
    finally:
        subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", str(work)], capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
        if not locals().get("resolved"):
            subprocess.run(["git", "-C", str(repo), "branch", "-D", branch], capture_output=True)
