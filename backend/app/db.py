from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import config
from .models import Base, CWECategory, User

CWES = [
    ("CWE-798", "Use of Hard-coded Credentials",
     "A credential is embedded in source code, so anyone with repository access (or history) can read it.", "High"),
    ("CWE-916", "Password Hash With Insufficient Computational Effort / Unprotected Storage (CWE-256)",
     "Passwords are stored in plaintext or with a fast, unsalted hash that can be cracked quickly.", "Medium"),
    ("CWE-89", "SQL Injection",
     "Untrusted input is concatenated into a SQL statement, letting an attacker change its meaning.", "High"),
    ("CWE-862", "Missing Authorization (Broken Access Control)",
     "A sensitive endpoint can be called without an authorisation check.", "Medium"),
]

connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(eng=engine) -> None:
    Base.metadata.create_all(eng)
    with sessionmaker(bind=eng)() as s:
        for cid, name, desc, sev in CWES:
            if not s.get(CWECategory, cid):
                s.add(CWECategory(cwe_id=cid, name=name, description=desc, default_severity=sev))
        if not s.query(User).count():
            s.add(User(name="Dev User", email="dev@legacyguard.local", role="developer"))
            s.add(User(name="Review User", email="reviewer@legacyguard.local", role="reviewer"))
        s.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
