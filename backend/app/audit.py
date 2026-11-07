"""Audit Trail & Logging: cross-cutting, append-only, hash-chained (REQ-007, Objective 3)."""
import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLogEntry, utcnow

GENESIS = "0" * 64


def _canon(ts) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S")  # tz-independent: SQLite drops tzinfo, hashes must still match


def _digest(prev, entity_type, entity_id, finding_id, action, detail, actor, ts) -> str:
    raw = "|".join(map(str, [prev, entity_type, entity_id, finding_id, action, detail, actor, _canon(ts)]))
    return hashlib.sha256(raw.encode()).hexdigest()


def log(db: Session, entity_type: str, entity_id: int, action: str, detail: str = "",
        actor: str = "system", finding_id: int | None = None) -> AuditLogEntry:
    last = db.execute(select(AuditLogEntry).order_by(AuditLogEntry.log_id.desc()).limit(1)).scalar()
    prev = last.entry_hash if last else GENESIS
    ts = utcnow().replace(microsecond=0)
    entry = AuditLogEntry(entity_type=entity_type, entity_id=entity_id, finding_id=finding_id, action=action,
                          detail=detail, actor=actor, timestamp=ts, prev_hash=prev,
                          entry_hash=_digest(prev, entity_type, entity_id, finding_id, action, detail, actor, ts))
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    rows = db.execute(select(AuditLogEntry).order_by(AuditLogEntry.log_id)).scalars().all()
    for r in rows:
        expected = _digest(prev, r.entity_type, r.entity_id, r.finding_id, r.action, r.detail, r.actor, r.timestamp)
        if r.prev_hash != prev or r.entry_hash != expected:
            return {"valid": False, "broken_at": r.log_id, "entries": len(rows)}
        prev = r.entry_hash
    return {"valid": True, "entries": len(rows)}
