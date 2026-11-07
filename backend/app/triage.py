"""LLM Triage Agent (Module 3).

propose() returns {"explanation", "popia_flag", "new_text"|None}. `new_text` replaces the single flagged source line.
With ANTHROPIC_API_KEY set it calls the Claude API (secrets are redacted before leaving the machine);
otherwise a deterministic offline fixer is used so the pipeline and tests run without network/cost.
"""
import json
import re

from . import config
from .scanner import CRED_RE, redact

POPIA_WORDS = re.compile(r"(?i)user|customer|order|payment|card|account|password|email|address|person")

EXPLAIN = {
    "CWE-798": "A credential is written directly in the source file. Anyone with read access to the repository "
               "(including its Git history) can see it, and it cannot be rotated without a code change.",
    "CWE-916": "Passwords are stored or hashed in a way that is cheap to reverse (plaintext or an unsalted fast "
               "hash). If the database leaks, customer passwords can be recovered quickly.",
    "CWE-89": "User-controlled input is concatenated into a SQL statement, so an attacker can alter the query "
              "(read or modify other customers' data). Parameterised queries remove the risk.",
    "CWE-862": "This admin/internal endpoint has no authorisation check, so any caller who can reach it may use it.",
}


def capabilities(root) -> dict:
    """What the target project already depends on, so templates never propose code that cannot compile."""
    from pathlib import Path
    pom = Path(root) / "pom.xml"
    if not pom.exists():
        return {"crypto": True, "security": True}
    t = pom.read_text(encoding="utf-8", errors="replace")
    sec = "spring-boot-starter-security" in t or "spring-security-core" in t
    return {"crypto": sec or "spring-security-crypto" in t, "security": sec}


def _offline_fix(cwe: str, line: str, rule: str = "", caps: dict | None = None) -> str | None:
    caps = caps or {"crypto": True, "security": True}
    if rule in ("lg-plaintext-password-lookup", "lg-controller-no-authz"):
        return None  # needs design changes (hash on write, add Spring Security): never auto-patched, human decides
    if rule == "lg-config-secret":
        key = line.split("=", 1)[0].strip()
        return f"{key}=${{{re.sub(r'[^A-Za-z0-9]+', '_', key).upper()}}}"
    if cwe == "CWE-798":
        m = CRED_RE.search(line)
        if m:
            var = re.search(r"String\s+(\w+)", m.group(1)).group(1)
            env = re.sub(r"(?<!^)(?=[A-Z])", "_", var).upper()
            return f'{m.group(1)}System.getenv("{env}");'
    if cwe == "CWE-916" and not caps["crypto"]:
        return None
    if cwe == "CWE-862" and not caps["security"]:
        return None
    if cwe == "CWE-916":
        if "NoOpPasswordEncoder.getInstance()" in line:
            return line.replace("NoOpPasswordEncoder.getInstance()", "new BCryptPasswordEncoder()")
        m = re.search(r"DigestUtils\.(?:md5|sha1)Hex\(([^)]*)\)", line)
        if m:
            return line.replace(m.group(0), f"new BCryptPasswordEncoder().encode({m.group(1)})")
    if cwe == "CWE-89":
        m = re.search(r'(?:([\w.<>\[\]]+)\s+)?(\w+)\s*=\s*(\w+)\.execute(Query|Update)\(\s*"([^"]*?)"\s*\+\s*(\w+)\s*\)', line)
        if m:
            typ, res, stmt, kind, sql, arg = m.groups()
            sql = re.sub(r"""\s*['"]?\s*$""", "", sql) + " ?"
            decl = f"{typ} " if typ else ""
            return "\n".join([f'java.sql.PreparedStatement ps = conn.prepareStatement("{sql.strip()}");',
                              f"ps.setObject(1, {arg});",
                              f"{decl}{res} = ps.execute{kind}();"])
    if cwe == "CWE-862":
        return "@PreAuthorize(\"hasRole('ADMIN')\")\n" + line.strip()
    return None


def _complete(system: str, user: str) -> str:
    if config.LLM_PROVIDER == "openai":
        import httpx
        r = httpx.post(config.LLM_BASE_URL.rstrip("/") + "/chat/completions", timeout=180,
                       headers={"Authorization": f"Bearer {config.LLM_API_KEY}"},
                       json={"model": config.LLM_MODEL, "temperature": 0,
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    import anthropic
    resp = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.create(
        model=config.CLAUDE_MODEL, max_tokens=800, system=system, messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in resp.content if b.type == "text")


def _claude_propose(finding: dict, context: str, prior: list[dict], feedback: str) -> dict:
    system = ("You are a secure-code reviewer for Java / Spring Boot. Reply with ONLY a JSON object: "
              '{"explanation": plain-language risk for a small-team developer (max 3 sentences), '
              '"popia_flag": "none"|"possible"|"likely" (South African POPIA exposure of personal data), '
              '"new_text": the replacement for the single flagged line (may be several lines; keep it minimal, '
              "compile-safe, no placeholders), or null if you cannot fix it safely}. "
              "Never output a real secret; read credentials from environment variables.")
    user = (f"Explain ONLY this issue (do not discuss other problems in the context): "
            f"{EXPLAIN.get(finding['cwe_id'], '')} Rule: {finding.get('rule_id', '')}.\n"
            f"CWE: {finding['cwe_id']}  File: {finding['file_path']}:{finding['line_number']}\n"
            f"Flagged line (redacted): {finding['snippet']}\nContext (redacted):\n{context}\n")
    if prior:
        user += "Earlier attempts that FAILED verification:\n" + "\n".join(
            f"- attempt {p['attempt']}: {p['new_text']!r}" for p in prior)
    if feedback:
        user += f"\nReviewer feedback to address: {feedback}\n"
    text = _complete(system, user)
    data = json.loads(text[text.index("{"): text.rindex("}") + 1])
    return {"explanation": data.get("explanation", ""), "popia_flag": data.get("popia_flag", "none"),
            "new_text": data.get("new_text")}


NO_AUTOPATCH = {"lg-plaintext-password-lookup", "lg-controller-no-authz"}  # need a design decision: explain, never patch
_RANK = {"none": 0, "possible": 1, "likely": 2}


def propose(finding: dict, source_line: str, context_lines: list[str], prior: list[dict] | None = None,
            feedback: str = "") -> dict:
    """Trusted deterministic template first; LLM only explains policy-blocked rules or patches unfamiliar cases."""
    prior = prior or []
    cwe, rule = finding["cwe_id"], finding.get("rule_id", "")
    blocked = rule in NO_AUTOPATCH
    caps = finding.get("caps")
    template = None if blocked else _offline_fix(cwe, source_line, rule, caps)
    needs_dep = not blocked and template is None and _offline_fix(cwe, source_line, rule) is not None
    if template and any(p["new_text"] == template for p in prior):
        template = None
    hint = " ".join([source_line, finding["file_path"]])
    popia = "likely" if cwe in ("CWE-916", "CWE-89") and POPIA_WORDS.search(hint) else         "possible" if POPIA_WORDS.search(hint) else "none"
    out = {"explanation": EXPLAIN.get(cwe, "Potential vulnerability."), "popia_flag": popia, "new_text": template,
           "final": blocked or needs_dep}
    if needs_dep:
        out["explanation"] += (" A safe automatic fix needs the Spring Security dependency, which this project does not "
                               "declare; add it (or choose another approach) and re-run.")
    if config.LLM_BASE_URL or config.ANTHROPIC_API_KEY:
        try:
            llm = _claude_propose(finding, chr(10).join(redact(l) for l in context_lines), prior, feedback)
            out["explanation"] = llm["explanation"] or out["explanation"]
            if _RANK.get(llm["popia_flag"], 0) > _RANK[popia]:
                out["popia_flag"] = llm["popia_flag"]
            if not blocked and not template and llm["new_text"]:
                out["new_text"] = llm["new_text"]
        except Exception as exc:  # degrade to the deterministic result, never block the pipeline
            out["explanation"] += f" (LLM unavailable: {type(exc).__name__}; template used.)"
    if feedback:
        out["explanation"] += f" Reviewer feedback noted: {feedback}"
    return out
