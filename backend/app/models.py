"""Data store: the 8-entity, 3NF schema from design Section 8.1.2 / Figure 4."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repository"
    repo_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000), unique=True)  # local path or remote URL
    language: Mapped[str] = mapped_column(String(50), default="java")


class User(Base):
    __tablename__ = "user_account"
    user_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    role: Mapped[str] = mapped_column(String(20))  # developer | reviewer


class CWECategory(Base):
    __tablename__ = "cwe_category"
    cwe_id: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. "CWE-798"
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    default_severity: Mapped[str] = mapped_column(String(10))


class Scan(Base):
    __tablename__ = "scan"
    scan_id: Mapped[int] = mapped_column(primary_key=True)
    repo_id: Mapped[int] = mapped_column(ForeignKey("repository.repo_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.user_id"))
    trigger: Mapped[str] = mapped_column(String(20), default="manual")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="running")
    findings: Mapped[list["Finding"]] = relationship(back_populates="scan")


class Finding(Base):
    __tablename__ = "finding"
    finding_id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scan.scan_id"))
    cwe_id: Mapped[str] = mapped_column(ForeignKey("cwe_category.cwe_id"))
    rule_id: Mapped[str] = mapped_column(String(100))
    file_path: Mapped[str] = mapped_column(String(1000))
    line_number: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(10))  # assessed severity of this instance
    snippet: Mapped[str] = mapped_column(Text)  # REDACTED display form, never the secret itself
    line_hash: Mapped[str] = mapped_column(String(64))  # sha256 of the stripped source line
    status: Mapped[str] = mapped_column(String(20), default="pending_triage")
    # pending_triage | awaiting_review | merged | rejected
    scan: Mapped[Scan] = relationship(back_populates="findings")
    cwe: Mapped[CWECategory] = relationship()
    fixes: Mapped[list["Fix"]] = relationship(back_populates="finding", order_by="Fix.attempt_number")


class Fix(Base):
    __tablename__ = "fix"
    fix_id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("finding.finding_id"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    explanation: Mapped[str] = mapped_column(Text, default="")
    popia_flag: Mapped[str] = mapped_column(String(20), default="none")  # none | possible | likely
    patch_diff: Mapped[str] = mapped_column(Text, default="")  # redacted unified diff for display
    branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verification_result: Mapped[str] = mapped_column(String(20), default="not_resolved")
    # resolved | not_resolved | build_failed | no_patch
    finding: Mapped[Finding] = relationship(back_populates="fixes")


class Review(Base):
    __tablename__ = "review"
    review_id: Mapped[int] = mapped_column(primary_key=True)
    fix_id: Mapped[int] = mapped_column(ForeignKey("fix.fix_id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user_account.user_id"))  # NFR-004
    decision: Mapped[str] = mapped_column(String(20))  # approve | reject | request_changes
    feedback: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLogEntry(Base):
    """Append-only, hash-chained log (REQ-007). Updates/deletes are rejected below."""
    __tablename__ = "audit_log_entry"
    log_id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int] = mapped_column(Integer)
    finding_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # query convenience
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(100), default="system")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))


@event.listens_for(AuditLogEntry, "before_update")
def _no_update(*_):
    raise PermissionError("audit log entries are immutable")


@event.listens_for(AuditLogEntry, "before_delete")
def _no_delete(*_):
    raise PermissionError("audit log entries cannot be deleted")
