"""FastAPI backend: the interface from design Section 3.2.3."""
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import audit, orchestrator
from .db import get_db, init_db
from .models import AuditLogEntry, Finding, User

app = FastAPI(title="LegacyGuard")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup():
    init_db()


def current_user(x_user_id: int = Header(...), db: Session = Depends(get_db)) -> User:
    user = db.get(User, x_user_id)
    if not user:
        raise HTTPException(401, "unknown user")
    return user


class ScanIn(BaseModel):
    repo_path: str


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "request_changes"]
    feedback: str = ""


def finding_out(f: Finding, detail: bool = False) -> dict:
    last = f.fixes[-1] if f.fixes else None
    out = {"id": f.finding_id, "cwe_id": f.cwe_id, "cwe_name": f.cwe.name, "severity": f.severity,
           "file_path": f.file_path, "line_number": f.line_number, "status": f.status,
           "verification": last.verification_result if last else None}
    if detail:
        out.update(snippet=f.snippet, attempts=[
            {"attempt": x.attempt_number, "explanation": x.explanation, "popia_flag": x.popia_flag,
             "patch_diff": x.patch_diff, "branch": x.branch, "verification": x.verification_result}
            for x in f.fixes])
        out["latest"] = out["attempts"][-1] if out["attempts"] else None
    return out


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/users")
def users(db: Session = Depends(get_db)):
    return [{"id": u.user_id, "name": u.name, "role": u.role} for u in db.query(User).all()]


@app.post("/scans")
def trigger_scan(body: ScanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        scan = orchestrator.run_scan(db, user, body.repo_path)
    except orchestrator.Forbidden as e:
        raise HTTPException(403, str(e))
    return {"scan_id": scan.scan_id, "status": scan.status, "findings": len(scan.findings)}


@app.get("/findings")
def list_findings(status: str | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Finding)
    if status:
        q = q.filter(Finding.status == ("awaiting_review" if status == "pending" else status))
    return [finding_out(f) for f in q.order_by(Finding.finding_id).all()]


ROOT_CAUSES = {
    "lg-controller-no-authz": "No authorization layer on the web API (one design gap, many endpoints)",
    "lg-plaintext-password-lookup": "Passwords stored and compared in plaintext",
    "lg-config-secret": "Secrets committed in configuration files",
    "lg-hardcoded-credential": "Credentials hard-coded in source",
    "lg-weak-password-storage": "Weak password hashing",
    "lg-sql-injection": "SQL built by string concatenation",
    "lg-missing-authz": "Sensitive endpoint without an authorization check",
}


@app.get("/findings/groups")
def finding_groups(_: User = Depends(current_user), db: Session = Depends(get_db)):
    """Reviewer-fatigue mitigation: one entry per root cause instead of one per occurrence."""
    groups: dict[str, dict] = {}
    for f in db.query(Finding).order_by(Finding.finding_id):
        g = groups.setdefault(f.rule_id, {"rule_id": f.rule_id, "cwe_id": f.cwe_id,
                                           "root_cause": ROOT_CAUSES.get(f.rule_id, f.rule_id), "severity": f.severity,
                                           "count": 0, "verified_fixes": 0, "locations": [], "finding_ids": []})
        g["count"] += 1
        g["verified_fixes"] += bool(f.fixes and f.fixes[-1].verification_result == "resolved")
        g["locations"].append(f"{f.file_path}:{f.line_number}")
        g["finding_ids"].append(f.finding_id)
    return sorted(groups.values(), key=lambda g: (g["severity"] != "High", -g["count"]))


@app.get("/findings/{finding_id}")
def get_finding(finding_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    f = db.get(Finding, finding_id)
    if not f:
        raise HTTPException(404, "finding not found")
    return finding_out(f, detail=True)


@app.post("/findings/{finding_id}/decision")
def decide(finding_id: int, body: DecisionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        f = orchestrator.decide(db, finding_id, user, body.decision, body.feedback)
    except orchestrator.Forbidden as e:
        raise HTTPException(403, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except orchestrator.Conflict as e:
        raise HTTPException(409, str(e))
    return finding_out(f, detail=True)


@app.get("/audit/verify")
def verify(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return audit.verify_chain(db)


@app.get("/audit/{finding_id}")
def get_audit(finding_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    f = db.get(Finding, finding_id)
    if not f:
        raise HTTPException(404, "finding not found")
    scan_entry = (AuditLogEntry.entity_type == "scan") & (AuditLogEntry.entity_id == f.scan_id)
    rows = db.query(AuditLogEntry).filter((AuditLogEntry.finding_id == finding_id) | scan_entry) \
        .order_by(AuditLogEntry.log_id).all()
    return [{"log_id": r.log_id, "timestamp": r.timestamp.isoformat(), "action": r.action, "detail": r.detail,
             "actor": r.actor} for r in rows]
