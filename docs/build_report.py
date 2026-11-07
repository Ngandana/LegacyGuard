"""Builds the Implementation and Testing/Evaluation report (.docx). All numbers are read from eval/results_*.json."""
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
EV = ROOT / "backend" / "eval"
OUT = ROOT / "docs"
IMG = OUT / "evidence"
B = json.loads((EV / "results_before.json").read_text())
A = json.loads((EV / "results_after.json").read_text())
RT = json.loads((EV / "real_template.json").read_text())
RL = json.loads((EV / "real_llm.json").read_text())
NAVY, TEAL, RED, AMBER = "#1f3864", "#00828f", "#c0392b", "#d68910"

# ------------------------------------------------------------------ charts
def chart_detection():
    cwes = ["CWE-798", "CWE-89", "CWE-916", "CWE-862"]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    w = 0.2
    for i, (lab, d, col) in enumerate([("Precision, initial rules", B, "#9bb1d4"), ("Precision, after fixes", A, NAVY)]):
        ax.bar([x + i * w - 0.3 for x in range(4)], [d["detection"]["per_cwe"][c]["precision"] for c in cwes], w, label=lab, color=col)
    for i, (lab, d, col) in enumerate([("Recall, initial rules", B, "#9fd6dc"), ("Recall, after fixes", A, TEAL)]):
        ax.bar([x + (i + 2) * w - 0.3 for x in range(4)], [d["detection"]["per_cwe"][c]["recall"] for c in cwes], w, label=lab, color=col)
    ax.set_xticks(range(4)); ax.set_xticklabels(cwes); ax.set_ylim(0, 1.15); ax.set_ylabel("Score")
    ax.legend(fontsize=7, ncol=2, loc="lower center"); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(IMG / "fig_detection.png", dpi=200); plt.close(fig)


def chart_gate():
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    labels = ["Scanner re-scan only\n(old verification)", "With build gate\n(initial templates)", "With build gate\n(after fixes)"]
    verified = [12, B["pipeline"]["outcome"].get("verified", 0), A["pipeline"]["outcome"].get("verified", 0)]
    rejected = [0, B["pipeline"]["outcome"].get("build_failed", 0), A["pipeline"]["outcome"].get("build_failed", 0)]
    esc = [0, B["pipeline"]["outcome"].get("escalated_no_fix", 0), A["pipeline"]["outcome"].get("escalated_no_fix", 0)]
    ax.bar(labels, verified, color=TEAL, label="Accepted as verified")
    ax.bar(labels, rejected, bottom=verified, color=RED, label="Rejected by build gate")
    ax.bar(labels, esc, bottom=[v + r for v, r in zip(verified, rejected)], color="#9aa5b1", label="Escalated to human, no auto-fix")
    ax.set_ylabel("Fixes (n = 12 defects + 1 class-level)"); ax.legend(fontsize=7); ax.spines[["top", "right"]].set_visible(False)
    plt.xticks(fontsize=8); fig.tight_layout(); fig.savefig(IMG / "fig_gate.png", dpi=200); plt.close(fig)


def llm_stats():
    rows = A["llm"]["rows"]
    t = [r["template"]["result"] for r in rows]; l = [r["local_llm"]["result"] for r in rows]
    return {"n": len(rows), "t_ok": t.count("resolved"), "l_ok": l.count("resolved"),
            "t_bf": t.count("build_failed"), "l_bf": l.count("build_failed"), "l_np": l.count("no_patch"),
            "l_nr": l.count("not_resolved"), "l_mean": round(statistics.mean(r["local_llm"]["seconds"] for r in rows), 1),
            "l_max": max(r["local_llm"]["seconds"] for r in rows)}


def chart_llm(s):
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    cats = ["Verified", "Rejected by gate", "Other (no patch / still flagged)"]
    t = [s["t_ok"], s["t_bf"], s["n"] - s["t_ok"] - s["t_bf"]]
    l = [s["l_ok"], s["l_bf"], s["n"] - s["l_ok"] - s["l_bf"]]
    x = range(3)
    ax.bar([i - 0.2 for i in x], t, 0.4, label="Deterministic template (no dependency check)", color=NAVY)
    ax.bar([i + 0.2 for i in x], l, 0.4, label="Local LLM (qwen2.5-coder 7B via Ollama)", color=AMBER)
    ax.set_xticks(list(x)); ax.set_xticklabels(cats, fontsize=8); ax.set_ylabel("Findings (n = %d)" % s["n"])
    ax.legend(fontsize=7); ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(IMG / "fig_llm.png", dpi=200); plt.close(fig)


S = llm_stats()
chart_detection(); chart_gate(); chart_llm(S)

# ------------------------------------------------------------------ docx helpers
doc = Document()
st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5)
for sec in doc.sections:
    sec.left_margin = sec.right_margin = Cm(2.2); sec.top_margin = sec.bottom_margin = Cm(2.0)
for lvl, size in ((1, 16), (2, 13), (3, 11)):
    h = doc.styles[f"Heading {lvl}"]; h.font.name = "Calibri"; h.font.size = Pt(size); h.font.color.rgb = RGBColor(0x1F, 0x38, 0x64)
FIG = [0]


def H(t, l=1): doc.add_heading(t, l)
def P(t, italic=False, bold=False):
    p = doc.add_paragraph(); r = p.add_run(t); r.italic = italic; r.bold = bold; p.paragraph_format.space_after = Pt(6); return p
def BUL(items):
    for i in items: doc.add_paragraph(i, style="List Bullet")


def shade(cell, hexcol):
    tcPr = cell._tc.get_or_add_tcPr(); sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hexcol); tcPr.append(sh)


def T(header, rows, widths=None, size=8.5):
    t = doc.add_table(rows=1, cols=len(header)); t.style = "Table Grid"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.text = ""; r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(size)
        r.font.color.rgb = RGBColor(255, 255, 255); shade(c, "1F3864")
    for ri, row in enumerate(rows):
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""; r = cells[i].paragraphs[0].add_run(str(v)); r.font.size = Pt(size)
            if ri % 2: shade(cells[i], "EEF2F7")
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths): row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def FIGURE(path, caption, width=15):
    doc.add_picture(str(path), width=Cm(width)); doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    FIG[0] += 1; c = P(f"Figure {FIG[0]}. {caption}", italic=True); c.alignment = WD_ALIGN_PARAGRAPH.CENTER


d_b, d_a = B["detection"], A["detection"]

# ------------------------------------------------------------------ cover
t = doc.add_paragraph(); r = t.add_run("POSTGRADUATE DIPLOMA IN ICT"); r.bold = True; r.font.size = Pt(12)
doc.add_paragraph("Capstone Project: Implementation and Testing/Evaluation Phase Submission")
T(["Item", "Detail"], [
    ["Project title", "Agentic AI-Based Development Tool for South African Software Industry (LegacyGuard)"],
    ["Student", "Sibabalwe Ngandana (220193894)"], ["Supervisor", "Dr Didi"], ["Stream", "Application Development"],
    ["Academic year", "2026"], ["Submission date", "7 November 2026"],
    ["Builds on", "Design Phase submission of 2 August 2026 (live document; Sections 3, 4, 6 and 8 of that submission remain the design of record)"]],
  [4, 12.5], 9.5)
P("Declaration: I declare that this submission is my own original work and has been prepared in accordance with the academic integrity policies of the institution.   Student signature: ______________________", italic=True)

H("Contents")
for line in ["1. Introduction and scope", "2. Implementation: structure and adherence to design (rubric A1)",
             "3. Functional completeness against requirements (A2)", "4. Test plan and coverage (B1)",
             "5. Test execution, results and defect register (B2)", "6. Evaluation results and analysis (C1)",
             "7. Critical evaluation against project objectives (C2)", "8. Technical documentation (D1)",
             "9. Security and maintainability (E1)", "10. Conclusion and preparation for demonstration",
             "11. References", "Appendix A: Evaluation fixture and reproduction commands", "Appendix B: Self-assessment against the rubric"]:
    doc.add_paragraph(line)

# ------------------------------------------------------------------ 1
H("1. Introduction and scope")
P("The Design Phase specified LegacyGuard, a pipeline in which static analysis detects vulnerabilities in legacy Java / Spring Boot "
  "backends, a large language model (LLM) agent explains each finding and proposes a fix, the fix is staged and verified on an "
  "isolated branch, and only a human reviewer can merge it, with every action recorded in an audit trail. This report documents "
  "the working implementation, how it was tested, and what the measured results show about whether the project objectives were met.")
P("The target codebase is the author's repository (github.com/Ngandana/African-Arts-Craft, branch master: Spring Boot 3.2.5, 127 Java "
  "files). Where this report says 'real repository' it means that codebase. Because that codebase contains few defects of each kind "
  "and no independently labelled ground truth, evaluation additionally uses a fixture of injected defects with known locations "
  "(Section 6, Appendix A). All results below were produced by commands that can be re-run (Appendix A); numbers are taken from saved result files.")
P("The design follows the detect, repair and validate pattern of recent work (Fakih et al., 2025; Gajjar et al., 2025). The four vulnerability classes are "
  "identified by their MITRE Common Weakness Enumeration entries (MITRE, n.d.), and personal-information exposure is considered against the Protection of Personal "
  "Information Act (Republic of South Africa, 2013).")
P("Honest framing: this is a single-author project evaluated on one real repository and one injected fixture. The results demonstrate "
  "that the design works and quantify specific behaviours; they do not establish general performance across the industry.", italic=True)

# ------------------------------------------------------------------ 2
H("2. Implementation: structure and adherence to design (A1)")
P("The implementation follows the four-tier, five-module architecture of the Design Phase (Section 3.1, Figure 1 of that document). "
  "Table 1 maps each designed component to its code module. Deviations are listed in Table 2 with justification.")
T(["Design element (Design Phase)", "Implemented in", "Notes"], [
    ["Module 1: Scan Orchestrator", "backend/app/orchestrator.py (run_scan, validate_scope)", "Scope validation restricts scans to allowed roots that are git repositories"],
    ["Module 2: Static Analysis Wrapper", "backend/app/scanner.py", "Built-in rules for the four CWE classes plus config-file secrets; Semgrep adapter and rules/legacyguard.yml (untested, see 9.2)"],
    ["Module 3: LLM Triage Agent", "backend/app/triage.py", "Deterministic templates first; LLM (Claude API or any OpenAI-compatible endpoint such as local Ollama) explains and, for unfamiliar cases, patches"],
    ["Module 4: Remediation Staging and Verification", "backend/app/staging.py, backend/app/build.py", "Git worktree on an isolated branch; re-scan; build and test gate (new, Section 3.2)"],
    ["Module 5: Human Review and Approval", "orchestrator.decide; frontend/src/App.jsx", "Only code path that merges; requires a reviewer and an approving Review record"],
    ["Audit Trail and Logging", "backend/app/audit.py; models.AuditLogEntry", "SHA-256 hash chain plus ORM guards against update/delete"],
    ["Data store, 8-entity 3NF schema (Figure 4)", "backend/app/models.py, db.py", "All eight entities implemented as designed; added Finding.rule_id, line_hash, status; Fix.popia_flag, branch"],
    ["Interface specification (Section 3.2.3)", "backend/app/main.py", "All five endpoints implemented; two added: /findings/groups, /audit/verify"],
    ["Reviewer dashboard (Figure 5, Screenshots 1-4)", "frontend/src (React, Vite, Tailwind)", "Findings list, detail, decision buttons, audit trail; root-cause panel added"]],
  [4.6, 5.4, 6.5])
P("Table 1. Mapping of designed components to implemented modules.", italic=True)
T(["Deviation from design", "Reason"], [
    ["SQLite is the default database; PostgreSQL is selected with DATABASE_URL", "Zero-setup local runs and fast tests. The schema uses only portable SQLAlchemy types. PostgreSQL was not exercised in this phase."],
    ["Built-in line-based rules are the primary detector; Semgrep is optional", "Semgrep is not available natively on the author's Windows machine. Detection quality is measured for the built-in engine only."],
    ["Template-first fixing; the LLM is secondary", "Evidence from testing (DEF-04, DEF-05): a 7B local model produced a wrong fix that passed re-scan, and failed on fixes a template handles. See Section 3.2."],
    ["Findings that need a design decision are never auto-patched", "Plaintext password lookups and controller-wide missing authorisation need architectural change; a one-line patch would be misleading."],
    ["Test directories are excluded from scanning", "Test fixtures were reported as production credentials (DEF-01)."]],
  [7, 9.5])
P("Table 2. Deviations from the approved design, with justification.", italic=True)
P("Code organisation and practice. Each module has one responsibility and no module imports a later pipeline stage; configuration is "
  "environment-driven (backend/app/config.py); persistence uses typed SQLAlchemy 2.0 models; the staging module contains no merge "
  "function, so the human-in-the-loop rule is enforced structurally rather than by convention. "
  "The evaluation harness (backend/eval) is separate from production code.")

# ------------------------------------------------------------------ 3
H("3. Functional completeness against requirements (A2)")
H("3.1 Requirement status", 2)
T(["ID", "Requirement (Design Phase, Section 6)", "Status", "Evidence"], [
    ["REQ-001", "Detect four vulnerability classes", "Met, with limits", "Table 7: precision and recall per CWE; line-based, not data-flow. Real repository: 20 findings in 3 root causes"],
    ["REQ-002", "Plain-language explanation, POPIA flag", "Met (flag only)", "Explanation per finding; POPIA flag is a keyword heuristic (none/possible/likely), not a mapping to POPIA sections"],
    ["REQ-003", "Specific, testable fix per finding", "Partly met", "Verified fixes for hard-coded credentials, config secrets and SQL injection. Password storage and authorisation findings are explained and escalated (Table 8)"],
    ["REQ-004", "Verify fix before reviewer sees it", "Met, strengthened", "Re-scan plus build and test gate (TC-09 to TC-11, Section 6.2)"],
    ["REQ-005", "Explicit human approval before merge", "Met", "TC-04, TC-05: target branch unchanged until an approving reviewer decision"],
    ["REQ-006", "Approve, reject, request changes", "Met", "TC-05; endpoint POST /findings/{id}/decision"],
    ["REQ-007", "Permanent, tamper-evident audit trail", "Met, with limit", "Hash chain verified (TC-06). Immutability is enforced in the ORM; a raw SQL edit is detected, not prevented"],
    ["REQ-008", "Bounded retries, then escalation", "Met", "TC-10: exactly three attempts then an 'escalated' audit entry"],
    ["REQ-009", "Explicit actor permissions", "Partly met", "Only decisions are role-restricted (reviewer). Scan and audit viewing are open to any authenticated user; see 9.2"],
    ["NFR-001", "No writes outside target or isolated branch", "Met", "TC-03, TC-07: base branch hash unchanged; path-traversal and out-of-scope paths rejected"],
    ["NFR-002", "Surface POPIA relevance", "Met (heuristic)", "popia_flag on every finding; real repository: 2 likely, 7 possible, 11 none"],
    ["NFR-003", "Demonstrable on a real codebase", "Met", "Section 6.4: scan of the author's repository, 3 s template-only, 147 s with local-LLM explanations"],
    ["NFR-004", "Attributable scans and decisions", "Met in schema, weak in practice", "User foreign keys implemented. Identity is a seeded X-User-Id header, not real authentication"]],
  [1.7, 4.7, 2.7, 7.4], 8)
P("Table 3. Requirement completeness. 'Met' means implemented and covered by an executed test or experiment.", italic=True)
H("3.2 Scope changes (documented and justified)", 2)
BUL([
    "Build and test gate added to verification. The Design Phase verified a fix by re-running the same static analyser that produced the finding. "
    "That is circular: a patch that deletes the vulnerable line, or breaks the build, clears the scanner. It was observed directly (DEF-04). "
    "SecureFixAgent, cited in the Design Phase, closes its loop by re-validating with the same static analyser that detects the issue (Gajjar et al., 2025), so adding compilation and regression tests is a deliberate extension of that pattern.",
    "Findings grouped by root cause. The first real scan produced 15 near-identical findings (one per controller), realising the 'reviewer fatigue' risk "
    "in the Design Phase risk table. The dashboard and GET /findings/groups now present one entry per root cause.",
    "Local-first LLM option. The problem statement cites unreliable electricity, limited connectivity and cost. A pipeline that needs a metered cloud API "
    "for every scan contradicts that, so the agent accepts any OpenAI-compatible endpoint and was evaluated with a local 7B model (Section 6.3).",
    "Dependency-aware fixing. Templates no longer propose code that needs a library the project does not declare (DEF-09)."])

# ------------------------------------------------------------------ 4
H("4. Test plan and coverage (B1)")
P("Strategy. Three levels are used. (1) Unit and integration tests exercise the pipeline through the real HTTP API against a temporary git repository "
  "(pytest, FastAPI TestClient, real git operations; only Maven is stubbed in gate tests for speed). (2) System-level experiments run the complete "
  "pipeline, with real Maven builds, on the real repository and on an injected-defect fixture. (3) User acceptance was not conducted with external users "
  "(Section 7); the reviewer workflow was exercised through the API. Each test case is traced to requirements in Table 4.")
T(["ID", "Test case", "Level", "Traces to"], [
    ["TC-01", "Scanner detects all four CWE classes in sample project (5 findings)", "Integration", "REQ-001"],
    ["TC-02", "Findings grouped by root cause; locations sum to findings", "Integration", "REQ-001, risk: reviewer fatigue"],
    ["TC-03", "Staged fixes are verified on branches; base branch hash unchanged", "Integration", "REQ-004, REQ-005, NFR-001"],
    ["TC-04", "Credential value never appears in API output or audit log", "Integration", "NFR-001, Section 9.3 security table"],
    ["TC-05", "Developer denied approval (403); reviewer approve merges; reject leaves branch untouched; request-changes re-triages; approve of rejected finding returns 409", "Integration", "REQ-005, REQ-006, REQ-009"],
    ["TC-06", "Audit trail ordered scan_started to merged; chain verifies; ORM update blocked; raw-SQL tamper detected", "Integration", "REQ-007, NFR-004"],
    ["TC-07", "Out-of-scope repository path rejected (403); path traversal rejected", "Unit", "NFR-001"],
    ["TC-08", "Approve returns 409 when no verified fix exists", "Integration", "REQ-005"],
    ["TC-09", "Patch that breaks compilation is not verified and cannot be approved", "Integration (Maven stubbed)", "REQ-004"],
    ["TC-10", "Rejected patch leads to exactly three attempts then an 'escalated' audit entry", "Integration", "REQ-008"],
    ["TC-11", "Patch that breaks existing tests is rejected; green build is verified; broken baseline does not block fixes", "Integration", "REQ-004"],
    ["EXP-A", "Detection precision/recall against injected ground truth (13 defects, 6 decoys)", "System experiment", "REQ-001"],
    ["EXP-B", "Full pipeline with real Maven build gate on injected fixture", "System experiment", "REQ-003, REQ-004"],
    ["EXP-C", "Template versus local LLM as patch author, same findings, same gate", "System experiment", "REQ-003, Objective 2"],
    ["EXP-D", "Scan of the real repository, template-only and with local-LLM explanations", "System experiment", "NFR-003, REQ-002, NFR-002"]],
  [1.5, 8.7, 3, 3.3], 8.5)
P("Table 4. Test plan with traceability to requirements.", italic=True)
P("Coverage. The automated suite measures line coverage of the application package at 83% (656 statements, 112 missed). Lowest coverage is in "
  "triage.py (62%), because the Claude/OpenAI-compatible call paths are exercised only by the experiments, not by unit tests, and in scanner.py (75%), "
  "where the Semgrep adapter is unexecuted. This is reported rather than hidden: those are the paths with least automated protection.")

# ------------------------------------------------------------------ 5
H("5. Test execution, results and defect register (B2)")
H("5.1 Automated tests", 2)
P("The suite was executed on 7 November 2026 on Windows 11 with Python 3.12.10, JDK 17.0.12 and Maven 3.10.0. Result: 12 passed, 0 failed, in 22 seconds "
  "(full output: docs/evidence/pytest_output.txt). Gate tests TC-09 to TC-11 stub Maven; the real Maven gate is exercised in EXP-B.")
T(["Module (app/)", "Statements", "Missed", "Coverage"], [
    ["models.py", 86, 1, "99%"], ["staging.py", 71, 3, "96%"], ["orchestrator.py", 106, 15, "86%"],
    ["scanner.py", 96, 24, "75%"], ["triage.py", 95, 36, "62%"], ["Total (all modules)", 656, 112, "83%"]], [5, 3, 3, 3], 9)
P("Table 5. Line coverage from pytest-cov (selected modules; full table in the evidence file).", italic=True)
H("5.2 Defect register", 2)
P("Defects were logged as found. Several were found by the experiments rather than by the unit tests, which is itself a finding about test design: "
  "the unit tests used a simple sample project and could not expose problems that depend on a real project's dependencies.")
T(["ID", "Defect", "Severity", "Found by", "Resolution"], [
    ["DEF-01", "Test-class fixtures reported as production credentials (6 false positives on real repository)", "Medium", "EXP-D (first scan)", "Fixed: test directories excluded"],
    ["DEF-02", "Secrets in application.properties not detected (real repository, false negative)", "High", "Manual inspection of EXP-D", "Fixed: rule lg-config-secret (3 findings)"],
    ["DEF-03", "Plaintext password comparison and missing controller authorisation not covered by rules", "High", "Manual inspection of EXP-D", "Fixed: rules lg-plaintext-password-lookup, lg-controller-no-authz"],
    ["DEF-04", "LLM fix for missing authorisation replaced the @RequestMapping line with a @CrossOrigin line, removing the route, yet passed re-scan verification", "Critical", "Local-LLM trial", "Fixed: build gate; design-level rules never auto-patched. Residual risk in 7.3"],
    ["DEF-05", "Local 7B model failed to patch config secrets that a template patches", "Medium", "Local-LLM trial", "Fixed: template first, LLM explains"],
    ["DEF-06", "7B model explained CORS instead of the actual issue", "Low", "Local-LLM trial", "Fixed: prompt constrained to the rule; re-run explanation matched"],
    ["DEF-07", "SQL template used PreparedStatement without import (3 of 3 SQL fixes rejected)", "High", "EXP-B gate", "Fixed: fully-qualified type"],
    ["DEF-08", "SQL template assigned an int update result to a ResultSet", "High", "EXP-B gate", "Fixed: original declared type preserved"],
    ["DEF-09", "Templates for password hashing and authorisation assumed Spring Security, absent from the project", "High", "EXP-B gate (6 rejections)", "Fixed: dependency-aware templates; escalate with explanation"],
    ["DEF-10", "Decoy strings ('Password', 'Bearer') flagged as credentials (2 false positives)", "Medium", "EXP-A", "Fixed with label heuristic; trade-off in 7.3"],
    ["DEF-11", "Class-level authorisation check was file-wide, missing a class with one protected method (1 false negative)", "Medium", "EXP-A", "Fixed: class block and unprotected-method check"],
    ["DEF-12", "Build gate silently skipped when baseline does not compile", "Medium", "EXP-B (inert first run)", "Mitigated: explicit warning in the audit entry. Open: result still shown as verified"],
    ["DEF-13", "Evaluation harness inserted dependency into dependencyManagement block", "Low", "EXP-B", "Fixed"]],
  [1.5, 6.3, 1.5, 3, 4.2], 8)
P("Table 6a. Defects found and resolved during implementation and testing.", italic=True)
T(["ID", "Open issue / justified deferral", "Priority"], [
    ["OPEN-01", "The real repository's own test suite does not compile at baseline (stale AddressServiceTest, 2 errors), so regression tests cannot gate fixes there. Reported, not repaired: it is the target, not the tool.", "Medium"],
    ["OPEN-02", "Verification proves the project compiles and tests pass, not that a fix is secure. A weak but compilable password hash would pass.", "High"],
    ["OPEN-03", "Authentication is a placeholder header; roles are enforced on decisions only.", "High for production, deferred"],
    ["OPEN-04", "Audit immutability is enforced in the ORM; PostgreSQL triggers or revoked UPDATE/DELETE are not implemented.", "Medium, deferred"],
    ["OPEN-05", "Semgrep adapter is untested; PostgreSQL untested.", "Low, deferred"],
    ["OPEN-06", "application.properties in the real repository contains populated secret values committed to git. Recommend rotating them; removal from history was not performed.", "High, owner action"]],
  [1.6, 12.4, 2.5], 8.5)
P("Table 6b. Open issues and deferrals.", italic=True)

# ------------------------------------------------------------------ 6
H("6. Evaluation results and analysis (C1)")
H("6.1 Experiment A: detection accuracy", 2)
P("The fixture adds two Java files to a clone of the real repository: 13 injected defects (marked GT in the source, with known lines) and 6 decoys "
  "(marked TN: safe code that resembles a defect, such as a parameterised query, an environment-variable password, and an authorised admin endpoint). "
  "Findings that existed before injection are excluded. A finding counts as a true positive only at the exact marked line and CWE.")
rows = []
for c in ["CWE-798", "CWE-89", "CWE-916", "CWE-862"]:
    x, y = d_b["per_cwe"][c], d_a["per_cwe"][c]
    rows.append([c, f"{x['TP']}/{x['FP']}/{x['FN']}", f"{x['precision']:.2f} / {x['recall']:.2f}", f"{y['TP']}/{y['FP']}/{y['FN']}", f"{y['precision']:.2f} / {y['recall']:.2f}"])
rows.append(["All", f"{d_b['total']['TP']}/{d_b['total']['FP']}/{d_b['total']['FN']}", f"{d_b['total']['precision']:.2f} / {d_b['total']['recall']:.2f}",
             f"{d_a['total']['TP']}/{d_a['total']['FP']}/{d_a['total']['FN']}", f"{d_a['total']['precision']:.2f} / {d_a['total']['recall']:.2f}"])
T(["CWE", "Initial rules TP/FP/FN", "Precision / recall", "After DEF-10, DEF-11 TP/FP/FN", "Precision / recall"], rows, [2.2, 3.6, 3.2, 4.2, 3.3], 8.5)
P("Table 7. Detection results on the injected fixture before and after the two heuristic fixes.", italic=True)
FIGURE(IMG / "fig_detection.png", "Precision and recall by CWE class, initial rules versus after fixes (injected fixture).", 13)
P("Interpretation. With the initial rules, precision was 0.86 and recall 0.92: two decoy strings were flagged and one class-level authorisation gap was missed. "
  "After fixing both, all 13 defects were found and no decoy was flagged. This result is optimistic and must not be read as the tool's true accuracy: the "
  "two fixes were designed after seeing the failures on this same fixture, the fixture is small, and its ground truth was written by the same author as the rules. "
  "A held-out fixture written by a second person is needed to support a general claim. The label heuristic also has a cost: a real hard-coded password that is "
  "purely alphabetic and under 16 characters (for example 'letmein') is now ignored.")
H("6.2 Experiment B: effect of the build and test gate", 2)
ob_b, ob_a = B["pipeline"]["outcome"], A["pipeline"]["outcome"]
T(["Verification method", "Verified", "Rejected by gate", "Escalated (no auto-fix)"], [
    ["Scanner re-scan only (original design)", "12 of 12", "0", "0"],
    ["With build gate, initial templates", f"{ob_b.get('verified', 0)} of 12", str(ob_b.get('build_failed', 0)), str(ob_b.get('escalated_no_fix', 0))],
    ["With build gate, after DEF-07 to DEF-09 fixes (13 findings incl. class-level)", f"{ob_a.get('verified', 0)} of 13", str(ob_a.get('build_failed', 0)), str(ob_a.get('escalated_no_fix', 0))]],
  [7.5, 2.5, 3.2, 3.5], 8.5)
P("Table 8. Fixes accepted by each verification method on the injected fixture (real Maven compile on JDK 17).", italic=True)
FIGURE(IMG / "fig_gate.png", "Outcome of verification by method. The scanner-only method accepted every fix.", 13)
P("Interpretation. The original verification method accepted all 12 proposed fixes. The compile gate showed that 9 of them did not build, which exposed three "
  "defects in the templates themselves (DEF-07 to DEF-09). After those fixes, 6 fixes are verified (all hard-coded credential and SQL injection fixes) and "
  "the 7 cases that need a dependency or a design decision are escalated to the reviewer with an explanation, rather than presented as fixes. "
  "The first run of this experiment also showed the gate being inert when the baseline did not compile (DEF-12), which is why that condition now produces a warning.")
H("6.3 Experiment C: local LLM versus deterministic templates", 2)
P(f"The same {S['n']} auto-patchable findings were patched twice: by the deterministic template, and by a local model (qwen2.5-coder 7B, Ollama, CPU only, no network). "
  "Both patches passed through the same re-scan and build gate. The template run here had no dependency check, to isolate what the model does.")
T(["Patch author", "Verified", "Rejected by build gate", "Other", "Mean generation time"], [
    ["Deterministic template", f"{S['t_ok']} of {S['n']}", str(S['t_bf']), str(S['n'] - S['t_ok'] - S['t_bf']), "under 0.1 s"],
    ["Local LLM, 7B, CPU", f"{S['l_ok']} of {S['n']}", str(S['l_bf']), f"{S['l_np']} no patch, {S['l_nr']} still flagged", f"{S['l_mean']} s (max {S['l_max']} s)"]],
  [4, 2.5, 3.5, 3.8, 3], 8.5)
P("Table 9. Template versus local LLM as patch author (same findings, same verification).", italic=True)
FIGURE(IMG / "fig_llm.png", "Verified versus rejected fixes by patch author (n = %d)." % S["n"], 13)
P("Interpretation. On this small sample the 7B model was clearly weaker than a template for patterns that have a known safe form, and slower. It did "
  "produce verified fixes for two password-hashing findings that the dependency-blind template could not, so it is not useless; but without a human reviewer and "
  "a gate its output would not be trustworthy (DEF-04). These results support the design decision to use the model for explanation and for cases without a "
  "template, behind the gate. They do not show that a larger local model, or the Claude API, would behave the same way; neither was benchmarked. Latency of "
  f"about {S['l_mean']} s per call on an ordinary laptop CPU is acceptable for an on-demand scan and removes both the per-scan cost and the need for connectivity.")
H("6.4 Experiment D: the real repository", 2)
T(["Root cause (rule)", "Findings", "Outcome"], [
    ["Secrets committed in configuration (lg-config-secret)", "3", "3 fixes verified (replaced by environment placeholders); build gate not applicable to .properties files"],
    ["Passwords stored and compared in plaintext (lg-plaintext-password-lookup)", "2", "Explained; escalated (design change)"],
    ["No authorisation on controllers (lg-controller-no-authz)", "15", "Explained; escalated (no security layer or dependency in project)"],
    ["Total", "20", f"3 verified; reviewer sees 3 root causes instead of 20 items; {RT['seconds']} s template-only, {RL['seconds']} s with local-LLM explanations"]],
  [7, 2, 7.5], 8.5)
P("Table 10. Scan of the author's repository with the final implementation.", italic=True)
P("Interpretation. Two things matter more than the count. First, 17 of 20 findings could not be auto-fixed, because the dominant weakness in this codebase is an "
  "absent control (no authentication or authorisation layer, no password hashing) rather than a bad line of code. Pattern-based detection finds present patterns "
  "well and absences poorly; the four-class scope reports the symptom (every controller is open) but cannot say what to build. Second, grouping reduced the reviewer's "
  "queue from 20 items to 3, which addresses the reviewer-fatigue risk identified in the Design Phase. Whether this makes review faster was not measured. "
  "The POPIA heuristic flagged 9 of 20 findings (2 likely, 7 possible); with no labelled set, its accuracy is unknown.")

# ------------------------------------------------------------------ 7
H("7. Critical evaluation against project objectives (C2)")
T(["Objective (Design Phase, Section 1.3)", "Verdict", "Evidence and shortcomings"], [
    ["1. Agentic pipeline that detects and explains within four CWE classes on a real legacy codebase", "Met, with limits",
     "End to end on the real repository (Table 10); detection P/R in Table 7. Limits: line-based rules, no data-flow analysis, optimistic fixture result, Semgrep untested, explanation quality not rated by developers."],
    ["2. Iterative remediation that proposes and verifies fixes without merging autonomously", "Mostly met",
     "Bounded three-attempt loop, isolated branches, no merge path without a reviewer (TC-03, TC-05, TC-10). Verified fixes exist for 3 of the 5 defect types; build gate added. Shortfall: verification confirms buildability, not security (OPEN-02), and iteration helps little because retries of a deterministic template repeat the same answer."],
    ["3. Transparent, immutable audit trail addressing the trust barrier (TechCabal, 2026)", "Partly met",
     "Hash-chained, ordered, per-finding trail with tamper detection (TC-06). Shortfall: tamper-evident rather than tamper-proof (OPEN-04); trust itself was not tested with South African developers, so the claim that it addresses the adoption barrier is untested."],
    ["4. Working prototype and walkthrough of the review-and-approval workflow", "Met",
     "Working React dashboard and API replace the static wireframes. Shortfall: the dashboard was built and compiled but no usability test was run, and placeholder authentication is used."],
    ["5. Complete traceability matrix linking requirements to design elements", "Met",
     "Tables 3 and 4 extend the Design Phase matrix to implementation and to test cases. Three requirements are only partly met (REQ-003, REQ-009, NFR-004 in practice)."]],
  [4.8, 2.2, 9.5], 8.5)
P("Table 11. Assessment of each objective.", italic=True)
H("7.1 What worked", 2)
BUL(["Separating detection, reasoning and action made faults attributable: every one of the 13 logged defects was traced to a specific stage.",
     "The build gate was the most valuable change; it converted 9 plausible but broken fixes into rejections and found three template defects the unit tests missed.",
     "Template-first fixing with the LLM behind a gate gave predictable results, and local execution is practical on an ordinary laptop."])
H("7.2 What did not work, or is unproven", 2)
BUL(["A 7B local model is not reliable enough to author fixes unsupervised; one of its fixes deleted a route and passed the scanner (DEF-04).",
     "Most real findings (17 of 20) were not auto-fixable, which limits how much effort the tool saves on a codebase like this one.",
     "No user study was done, so the claims about reviewer fatigue and trust remain design arguments supported only by the grouping and audit mechanisms existing."])
H("7.3 Threats to validity", 2)
BUL(["Construct: 'verified' means re-scan clear plus compile (and tests where runnable). On the real repository the existing tests do not compile, so no regression testing occurred there.",
     "Internal: heuristics were tuned on the same fixture they were then scored on (Table 7). Ground truth and rules share one author.",
     "External: one real repository and one fixture; one local model; single run each (the experiments are deterministic except for LLM output, which was run once at temperature 0).",
     "Residual semantic risk: a compilable but weaker fix (for example a different fast hash) would pass the gate."])

# ------------------------------------------------------------------ 8
H("8. Technical documentation (D1)")
H("8.1 Setup and run", 2)
BUL(["Prerequisites: Python 3.12, Node 24, Git; for the build gate JDK 17 and Maven 3.10 (JAVA_HOME and MAVEN_HOME set); optional Ollama with 'ollama pull qwen2.5-coder:7b'.",
     "Backend: cd backend; python -m venv .venv; pip install -r requirements.txt; python -m pytest -q (expects 12 passed).",
     "Run: from the repository root, .\\run.ps1 starts the API on port 8000 and the dashboard on port 5173. Paste the path of the target repository and select Trigger scan. "
     "Set LEGACYGUARD_BASE_BRANCH if the target's default branch is not main (the author's repository uses master).",
     "Free local LLM: set LLM_BASE_URL=http://localhost:11434/v1 and LLM_MODEL=qwen2.5-coder:7b. Paid alternative: ANTHROPIC_API_KEY. Without either, templates are used.",
     "Database: SQLite by default; DATABASE_URL selects PostgreSQL (install psycopg)."])
H("8.2 Key technical decisions", 2)
BUL(["Deterministic templates before LLM output, so a known safe pattern is never at the mercy of a small model.",
     "Secrets are redacted at the scanner, so the redacted form is all that is stored, displayed, logged or sent to a model; the original line is re-read locally from git only when a patch is applied.",
     "Fixes are located by the SHA-256 of the original line rather than by line number, so earlier merges that shift lines do not misplace a later patch.",
     "The staging module has no merge capability; merging exists only in orchestrator.decide behind a reviewer check.",
     "Findings needing design decisions are explained but never auto-patched."])
H("8.3 Extending the system", 2)
P("To add a vulnerability class: add a detection rule in scanner.py and a CWECategory row in db.py; optionally add a template in triage._offline_fix and, if the "
  "fix needs a library, a flag in triage.capabilities. No change to the orchestrator, staging or API is required, as the Design Phase intended.")
H("8.4 Test results summary", 2)
P("12 of 12 automated tests pass (83% line coverage). Experiments A to D results are in Tables 7 to 10; raw outputs are in backend/eval/results_before.json, results_after.json, real_template.json and real_llm.json.")

# ------------------------------------------------------------------ 9
H("9. Security and maintainability (E1)")
H("9.1 Measures implemented", 2)
BUL(["Credential redaction at the source (TC-04); no secret is stored in the database, audit log, API response or LLM prompt.",
     "Scope control: scans are limited to allowed roots that are git repositories; file paths are resolved and must stay inside the checkout (TC-07).",
     "The target branch is changed only by an approved reviewer decision; fixes live on isolated branches that are deleted if verification fails.",
     "Reviewer-only decision endpoint; the schema attributes every scan and review to a user.",
     "Hash-chained audit log with an integrity endpoint (GET /audit/verify)."])
H("9.2 Known weaknesses", 2)
BUL(["Authentication is a trusted request header; anyone who can reach the API can claim to be the reviewer. This is unacceptable outside a demonstration.",
     "Audit immutability is not enforced by the database; a privileged user can alter rows, which the chain would detect but not prevent.",
     "Cross-origin access is restricted to the local dashboard origin, but there is no rate limiting or request size limiting.",
     "Semgrep, PostgreSQL and the Claude API path were not exercised.",
     "Maintainability: the scanner's regular expressions are dense and the Java templates are string-based; a parser-based approach would be more robust for a second language or framework."])

# ------------------------------------------------------------------ 10
H("10. Conclusion and preparation for demonstration")
P("The implementation realises the Design Phase architecture and was tested at unit, integration and system level. Its most significant result is negative evidence "
  "for the original design: verifying a fix by re-running the scanner is circular, and adding a build gate changed the acceptance of fixes from 12 of 12 to 6 of 13 "
  "(with the remainder escalated honestly). The tool is useful as a triage and review aid; it is not a substitute for a security engineer, and on the author's own "
  "repository most findings reflect missing controls that no automated patch should supply.")
P("For the demonstration the following are planned: a live scan of the real repository showing the three root causes; approval of a verified configuration-secret fix and "
  "inspection of its audit trail; a rejected fix; and the build gate rejecting a deliberately broken patch. Recommended next work: a held-out evaluation fixture written by a "
  "second person, real authentication, database-level audit protection, and a small usability test with developers.")

# ------------------------------------------------------------------ 11
H("11. References")
for ref in [
    "Fakih, M., Dharmaji, R., Bouzidi, H., Quiros Araya, G., Ogundare, O. and Al Faruque, M.A. (2025) LLM4CVE: enabling iterative automated vulnerability repair with large language models. arXiv:2501.03446. Available at: https://arxiv.org/pdf/2501.03446 (Accessed: 2 August 2026).",
    "Gajjar, J., Subramaniakuppusamy, K., Puthal, R. and Ranaware, K. (2025) SecureFixAgent: a hybrid LLM agent for automated Python static vulnerability repair. arXiv:2509.16275. Available at: https://arxiv.org/pdf/2509.16275 (Accessed: 1 August 2026).",
    "MITRE (n.d.) Common Weakness Enumeration: CWE-89, CWE-798, CWE-862, CWE-916. Available at: https://cwe.mitre.org (Accessed: 7 November 2026).",
    "Republic of South Africa (2013) Protection of Personal Information Act 4 of 2013. Pretoria: Government Printer.",
    "TechCabal (2026) South Africa's AI skills gap is widening faster than universities can adapt. Available at: https://techcabal.com (Accessed: 27 July 2026)."
    ]:
    p = doc.add_paragraph(ref); p.paragraph_format.left_indent = Cm(0.8); p.paragraph_format.first_line_indent = Cm(-0.8)
# ------------------------------------------------------------------ appendices
H("Appendix A: Evaluation fixture and reproduction commands")
P("Fixture files: backend/eval/fixtures/InjectedDefects.java and InjectedAdminController.java. Ground truth is carried in the source as '// GT:CWE-n' and decoys as '// TN'. "
  "Reproduce (from backend, after the setup in Section 8.1): python -m eval.run_eval after --llm  (writes eval/results_after.json; needs Ollama running for the LLM part); "
  "python -m eval.real_repo [--llm]  (real repository). Tests with coverage: python -m pytest -v --cov=app.")
H("Appendix B: Self-assessment against the rubric")
T(["Criterion", "Where evidenced", "Candid note"], [
    ["A1 Code structure and adherence to design", "Section 2, Tables 1 and 2", "Close mapping; documented deviations. The project folder was not yet under version control when this report was generated; commit history should be established before submission."],
    ["A2 Functionality completeness", "Section 3, Table 3", "Most requirements met; three partly met and stated as such."],
    ["B1 Test plan and coverage", "Section 4, Table 4", "Traced to requirements; no external user acceptance testing."],
    ["B2 Execution, results, defects", "Section 5, Tables 5 to 6b", "Real executions and a 13-item defect register with open issues."],
    ["C1 Presentation of results", "Section 6, Tables 7 to 10, Figures 1 to 3", "Interpretation includes limitations; fixture result flagged as optimistic."],
    ["C2 Critical evaluation", "Section 7", "Each objective assessed with shortcomings and threats to validity."],
    ["D1 Documentation", "Section 8, README", "Setup, decisions, extension guide."],
    ["E1 Security and maintainability", "Section 9", "Strengths and serious weaknesses both listed."]],
  [5, 5, 6.5], 8.5)

out = OUT / "LegacyGuard_Implementation_Testing_Evaluation_Report.docx"
doc.save(out)
print("saved", out, "figures:", FIG[0])
