"""Evaluation harness (Testing/Evaluation phase).

Usage: python -m eval.run_eval <tag> [--llm]
 1. clones the real African-Arts-Craft repo, injects fixture files with ground-truth markers (GT:/TN) and a
    commons-codec dependency so the injected code compiles;
 2. Experiment A: detection precision/recall per CWE against the markers (pre-existing real findings excluded);
 3. Experiment B: full pipeline with the build gate: how many proposed fixes are verified / rejected by the gate;
 4. Experiment C (--llm): local LLM (Ollama) as the patch author vs the deterministic template: validity + latency.
Results are written to eval/results_<tag>.json.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT / "eval_work"
SRC_REPO = ROOT / "targets" / "african-arts-craft"
TARGET = WORK / "target"

os.environ.update(DATABASE_URL=f"sqlite:///{WORK / 'eval.db'}", LEGACYGUARD_BASE_BRANCH="master",
                  LEGACYGUARD_ALLOWED_ROOTS=str(ROOT))
for k in ("ANTHROPIC_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
    os.environ.pop(k, None)
os.environ.setdefault("JAVA_HOME", r"C:\Program Files\Java\jdk-17")
os.environ["PATH"] += os.pathsep + str(Path.home() / "tools" / "maven" / "bin") + os.pathsep + os.environ["JAVA_HOME"] + r"\bin"
sys.path.insert(0, str(HERE.parent))

from app import build, config, db as dbmod, orchestrator, scanner, staging, triage  # noqa: E402
from app.models import Finding, User  # noqa: E402

GT_RE = re.compile(r"//\s*GT:(CWE-\d+)")
TN_RE = re.compile(r"//\s*TN\b")
INJECT_DIR = "src/main/java/za/ac/cput/eval"


def sh(*a, cwd=TARGET):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def prepare() -> set:
    if WORK.exists():
        shutil.rmtree(WORK, onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
    WORK.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", str(SRC_REPO), str(TARGET)], check=True)
    sh("git", "checkout", "-q", "master")
    before = {(f["rule_id"], f["file_path"], f["line_number"]) for f in scanner.run_static_analysis(TARGET)}
    dest = TARGET / INJECT_DIR
    dest.mkdir(parents=True)
    for f in (HERE / "fixtures").glob("*.java"):
        shutil.copy(f, dest / f.name)
    pom = (TARGET / "pom.xml").read_text(encoding="utf-8")
    dep = ("<dependency><groupId>commons-codec</groupId><artifactId>commons-codec</artifactId>"
           "<version>1.16.1</version></dependency>")
    (TARGET / "pom.xml").write_text(pom[:pom.rindex("</dependencies>")] + dep + pom[pom.rindex("</dependencies>"):], encoding="utf-8")
    sh("git", "-c", "user.name=eval", "-c", "user.email=e@e", "add", "-A")
    sh("git", "-c", "user.name=eval", "-c", "user.email=e@e", "commit", "-q", "-m", "inject evaluation fixtures")
    return before


def ground_truth():
    gt, tn = {}, set()
    for f in (TARGET / INJECT_DIR).glob("*.java"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            rel = f"{INJECT_DIR}/{f.name}"
            if m := GT_RE.search(line):
                gt[(rel, i)] = m.group(1)
            if TN_RE.search(line):
                tn.add((rel, i))
    return gt, tn


def detection(before: set, gt, tn) -> dict:
    found = [f for f in scanner.run_static_analysis(TARGET)
             if (f["rule_id"], f["file_path"], f["line_number"]) not in before and f["file_path"].startswith(INJECT_DIR)]
    flagged = {(f["file_path"], f["line_number"]): f["cwe_id"] for f in found}
    per = defaultdict(lambda: {"TP": 0, "FP": 0, "FN": 0})
    for key, cwe in gt.items():
        if flagged.get(key) == cwe:
            per[cwe]["TP"] += 1
        else:
            per[cwe]["FN"] += 1
    fp_lines = []
    for key, cwe in flagged.items():
        if key not in gt:
            per[cwe]["FP"] += 1
            fp_lines.append({"at": f"{key[0].split('/')[-1]}:{key[1]}", "cwe": cwe, "was_decoy": key in tn})
    for cwe, d in per.items():
        d["precision"] = round(d["TP"] / (d["TP"] + d["FP"]), 2) if d["TP"] + d["FP"] else None
        d["recall"] = round(d["TP"] / (d["TP"] + d["FN"]), 2) if d["TP"] + d["FN"] else None
    tot = {k: sum(d[k] for d in per.values()) for k in ("TP", "FP", "FN")}
    tot["precision"] = round(tot["TP"] / (tot["TP"] + tot["FP"]), 2)
    tot["recall"] = round(tot["TP"] / (tot["TP"] + tot["FN"]), 2)
    return {"per_cwe": dict(per), "total": tot, "false_positives": fp_lines,
            "missed": [f"{k[0].split('/')[-1]}:{k[1]} ({v})" for k, v in gt.items() if flagged.get(k) != v]}


def pipeline(gt) -> dict:
    dbmod.init_db()
    t = time.time()
    rows = []
    with dbmod.SessionLocal() as s:
        orchestrator.run_scan(s, s.get(User, 1), str(TARGET))
        for f in s.query(Finding).filter(Finding.file_path.like(f"{INJECT_DIR}%")):
            if (f.file_path, f.line_number) not in gt:
                continue
            rows.append({"finding": f"{f.file_path.split('/')[-1]}:{f.line_number}", "cwe": f.cwe_id, "rule": f.rule_id,
                         "attempts": [x.verification_result for x in f.fixes],
                         "final": f.fixes[-1].verification_result if f.fixes else None,
                         "gate_note": next((a.detail for a in _audit(s, f.finding_id) if "build gate" in a.detail), "")})
    outcome = defaultdict(int)
    for r in rows:
        outcome["verified" if "resolved" in r["attempts"] else "build_failed" if "build_failed" in r["attempts"]
                else "escalated_no_fix"] += 1
    return {"seconds": round(time.time() - t), "rows": rows, "outcome": dict(outcome), "n": len(rows)}


def _audit(s, fid):
    from app.models import AuditLogEntry
    return s.query(AuditLogEntry).filter(AuditLogEntry.finding_id == fid, AuditLogEntry.action == "fix_attempt").all()


def llm_experiment(gt) -> dict:
    """Same findings, patch authored by (a) the deterministic template, (b) a local LLM; both verified by the gate."""
    config.LLM_BASE_URL, config.LLM_MODEL, config.LLM_PROVIDER = "http://localhost:11434/v1", "qwen2.5-coder:7b", "openai"
    rows = []
    for f in [x for x in scanner.run_static_analysis(TARGET) if x["file_path"].startswith(INJECT_DIR)
              and x["rule_id"] not in triage.NO_AUTOPATCH and (x["file_path"], x["line_number"]) in gt]:
        line, ctx = staging.read_source(TARGET, f["file_path"], f["line_hash"], f["line_number"], "master")
        rec = {"finding": f"{f['file_path'].split('/')[-1]}:{f['line_number']}", "cwe": f["cwe_id"]}
        for who in ("template", "local_llm"):
            t = time.time()
            try:
                new = triage._offline_fix(f["cwe_id"], line, f["rule_id"]) if who == "template" else \
                    triage._claude_propose(f, "\n".join(scanner.redact(x) for x in ctx), [], "")["new_text"]
            except Exception as e:  # noqa: BLE001
                new = None
                rec[who + "_error"] = type(e).__name__
            gen = round(time.time() - t, 1)
            res = staging.apply_and_rescan(TARGET, "master", f"eval/{who}-{abs(hash((f['file_path'], f['line_number']))) % 10**6}", f, new)
            rec[who] = {"seconds": gen, "result": res["result"], "detail": res["detail"][-120:]}
        rows.append(rec)
    return {"rows": rows}


if __name__ == "__main__":
    tag = sys.argv[1]
    before = prepare()
    gt, tn = ground_truth()
    out = {"tag": tag, "ground_truth_defects": len(gt), "decoys": len(tn), "real_findings_excluded": len(before)}
    out["detection"] = detection(before, gt, tn)
    print(json.dumps(out["detection"]["total"]), flush=True)
    out["pipeline"] = pipeline(gt)
    print(json.dumps(out["pipeline"]["outcome"]), flush=True)
    if "--llm" in sys.argv:
        out["llm"] = llm_experiment(gt)
    (HERE / f"results_{tag}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("done", tag)
