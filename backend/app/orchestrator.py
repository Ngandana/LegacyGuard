"""Scan Orchestrator (Module 1) + the triage-and-fix loop (Section 3.2.2) + Human Review merge (Module 5)."""
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from . import audit, config, staging, triage
from .models import Finding, Fix, Repository, Review, Scan, User
from .scanner import run_static_analysis


class Forbidden(Exception):
    pass


class Conflict(Exception):
    pass


def validate_scope(path: str) -> Path:
    p = Path(path).resolve()
    if not any(r == p or r in p.parents for r in config.ALLOWED_ROOTS):
        raise Forbidden("target repository is outside the allowed roots")
    if not (p / ".git").exists():
        raise Forbidden("target is not a git repository")
    return p


def run_scan(db: Session, user: User, repo_path: str, trigger: str = "manual") -> Scan:
    root = validate_scope(repo_path)
    repo = db.query(Repository).filter_by(url=str(root)).first() or Repository(name=root.name, url=str(root))
    db.add(repo)
    db.flush()
    scan = Scan(repo_id=repo.repo_id, user_id=user.user_id, trigger=trigger)
    db.add(scan)
    db.flush()
    audit.log(db, "scan", scan.scan_id, "scan_started", f"scan of {root.name} ({config.BASE_BRANCH})", user.name)
    for f in run_static_analysis(root):
        finding = Finding(scan_id=scan.scan_id, **f)
        db.add(finding)
        db.flush()
        audit.log(db, "finding", finding.finding_id, "finding_recorded",
                  f"{f['cwe_id']} at {f['file_path']}:{f['line_number']}", "static-analysis-wrapper", finding.finding_id)
        triage_and_fix(db, finding, root)
    scan.status = "complete"
    audit.log(db, "scan", scan.scan_id, "scan_complete", f"{len(scan.findings)} findings", "system")
    db.commit()
    return scan


def _finding_dict(f: Finding) -> dict:
    return dict(cwe_id=f.cwe_id, rule_id=f.rule_id, file_path=f.file_path, line_number=f.line_number,
                snippet=f.snippet, line_hash=f.line_hash)


def triage_and_fix(db: Session, finding: Finding, root: Path, feedback: str = "") -> None:
    """Bounded loop: up to MAX_ATTEMPTS automated attempts, then always escalate to a human (REQ-008)."""
    fd = _finding_dict(finding)
    fd["caps"] = triage.capabilities(root)
    try:
        line, ctx = staging.read_source(root, fd["file_path"], fd["line_hash"], fd["line_number"], config.BASE_BRANCH)
    except staging.StagingError as e:
        audit.log(db, "finding", finding.finding_id, "triage_failed", str(e), "triage-agent", finding.finding_id)
        finding.status = "awaiting_review"
        return
    prior: list[dict] = []
    start = len(finding.fixes)
    for n in range(1, config.MAX_ATTEMPTS + 1):
        attempt = start + n
        out = triage.propose(fd, line, ctx, prior, feedback)
        audit.log(db, "finding", finding.finding_id, "explanation_generated",
                  f"popia={out['popia_flag']}", "triage-agent", finding.finding_id)
        branch = f"fix/legacyguard-{finding.finding_id}-a{attempt}"
        res = staging.apply_and_rescan(root, config.BASE_BRANCH, branch, fd, out["new_text"])
        fix = Fix(finding_id=finding.finding_id, attempt_number=attempt, explanation=out["explanation"],
                  popia_flag=out["popia_flag"], patch_diff=res["diff"], branch=res["branch"],
                  verification_result=res["result"])
        db.add(fix)
        db.flush()
        finding.fixes.append(fix)
        audit.log(db, "fix", fix.fix_id, "fix_attempt", f"attempt {attempt}: {res['result']} - {res['detail']}",
                  "staging", finding.finding_id)
        if res["result"] == "resolved":
            break
        if out.get("final"):  # policy-blocked rule: retrying cannot help, escalate now
            audit.log(db, "finding", finding.finding_id, "escalated",
                      "needs a design decision; automated patching is disabled for this rule", "system", finding.finding_id)
            break
        prior.append({"attempt": attempt, "new_text": out["new_text"]})
    else:
        audit.log(db, "finding", finding.finding_id, "escalated",
                  f"{config.MAX_ATTEMPTS} attempts used without a verified fix", "system", finding.finding_id)
    finding.status = "awaiting_review"


def decide(db: Session, finding_id: int, reviewer: User, decision: str, feedback: str = "") -> Finding:
    if reviewer.role != "reviewer":
        raise Forbidden("only a reviewer may decide")
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise LookupError("finding not found")
    if finding.status != "awaiting_review" or not finding.fixes:
        raise Conflict(f"finding is {finding.status}, not awaiting review")
    fix = finding.fixes[-1]
    review = Review(fix_id=fix.fix_id, user_id=reviewer.user_id, decision=decision, feedback=feedback)
    db.add(review)
    db.flush()
    audit.log(db, "review", review.review_id, "reviewed", f"{decision} by {reviewer.name}", reviewer.name,
              finding.finding_id)
    root = Path(db.get(Repository, finding.scan.repo_id).url)
    if decision == "approve":
        if fix.verification_result != "resolved" or not fix.branch:
            db.rollback()
            raise Conflict("cannot approve: no verified fix branch exists; reject or request changes")
        if staging.git(root, "rev-parse", "--abbrev-ref", "HEAD") != config.BASE_BRANCH:
            db.rollback()
            raise Conflict(f"target repository is not on {config.BASE_BRANCH}")
        try:
            staging.git(root, "-c", "user.name=LegacyGuard", "-c", "user.email=legacyguard@local", "merge", "--no-ff",
                        "-q", "-m", f"LegacyGuard: merge {fix.branch} (approved by {reviewer.name})", fix.branch)
        except staging.StagingError as e:
            subprocess.run(["git", "-C", str(root), "merge", "--abort"], capture_output=True)
            db.rollback()
            raise Conflict(f"merge conflict; re-scan to regenerate this fix ({e})")
        staging.git(root, "branch", "-D", fix.branch)
        finding.status = "merged"
        audit.log(db, "fix", fix.fix_id, "merged", f"{fix.branch} merged to {config.BASE_BRANCH}", "version-control",
                  finding.finding_id)
    elif decision == "reject":
        finding.status = "rejected"
    elif decision == "request_changes":
        finding.status = "pending_triage"
        triage_and_fix(db, finding, root, feedback)
    else:
        raise Conflict("unknown decision")
    db.commit()
    return finding
