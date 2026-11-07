"""Scan the real target and summarise (run with/without LLM_BASE_URL)."""
import json, os, sys, time, collections
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
os.environ.update(DATABASE_URL=f"sqlite:///{ROOT/'eval_work_real.db'}", LEGACYGUARD_BASE_BRANCH="master", LEGACYGUARD_ALLOWED_ROOTS=str(ROOT))
os.environ["PATH"] += os.pathsep + str(Path.home()/"tools"/"maven"/"bin")
if "--llm" in sys.argv:
    os.environ.update(LLM_BASE_URL="http://localhost:11434/v1", LLM_MODEL="qwen2.5-coder:7b")
sys.path.insert(0, str(ROOT/"backend"))
from app import db, orchestrator
from app.models import User, Finding
db.init_db(); t = time.time()
with db.SessionLocal() as s:
    orchestrator.run_scan(s, s.get(User, 1), str(ROOT/"targets"/"african-arts-craft"))
    rows = [(f.rule_id, f.cwe_id, f.fixes[-1].verification_result, len(f.fixes), f.fixes[-1].popia_flag) for f in s.query(Finding)]
c = collections.Counter(r[0] for r in rows)
out = {"seconds": round(time.time()-t), "findings": len(rows), "by_rule": c,
       "verified": sum(r[2] == "resolved" for r in rows), "popia": dict(collections.Counter(r[4] for r in rows))}
print(json.dumps(out))
