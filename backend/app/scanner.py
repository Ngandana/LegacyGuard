"""Static Analysis Wrapper (Module 2).

Runs the built-in rule engine for the four in-scope classes and, if the `semgrep` binary is on PATH,
Semgrep with rules/legacyguard.yml as well. Both are normalised to one Finding shape and de-duplicated.
Secrets are redacted in `snippet` so they never reach the DB, the audit log or the UI.
"""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from . import config

IGNORE_DIRS = {".git", "target", "build", "node_modules", ".idea", "test"}  # tests hold fixtures, not prod secrets

CRED_RE = re.compile(r'(?i)\b(String\s+\w*(?:password|passwd|secret|api_?key|token)\w*\s*=\s*)"([^"]+)"\s*;')
WEAK_PW_RE = re.compile(r'NoOpPasswordEncoder\.getInstance\(\)|DigestUtils\.(?:md5|sha1)Hex\(')
PROP_SECRET_RE = re.compile(r'(?i)^(\s*[\w.\-]*(?:password|secret|secretkey|accesskeyid|api[_-]?key|token)[\w.\-]*\s*=\s*)(?!\$\{)(\S.*)$')
PLAIN_LOOKUP_RE = re.compile(r'[A-Za-z]*By[A-Za-z]*AndPassword[A-Za-z]*\(')
CLASS_MAPPING_RE = re.compile(r'^@RequestMapping\(')
SQLI_RE = re.compile(r'\.execute(?:Query|Update)\(\s*"[^"]*"\s*\+\s*\w+')
MAPPING_RE = re.compile(r'@(?:Get|Post|Put|Delete|Patch|Request)Mapping\(\s*(?:value\s*=\s*)?"([^"]*)"')
AUTHZ_RE = re.compile(r'@(?:PreAuthorize|Secured|RolesAllowed)')
SENSITIVE_PATH_RE = re.compile(r'(?i)/(admin|internal|manage)')


def looks_like_label(value: str) -> bool:
    """Short purely-alphabetic values ("Password", "Bearer") are UI labels / type names, not credentials."""
    return len(value) < 16 and re.fullmatch(r"[A-Za-z _\-]+", value) is not None


def line_hash(line: str) -> str:
    return hashlib.sha256(line.strip().encode()).hexdigest()


def redact(line: str) -> str:
    line = CRED_RE.sub(lambda m: f'{m.group(1)}"***REDACTED***";', line.rstrip())
    return PROP_SECRET_RE.sub(lambda m: f"{m.group(1)}***REDACTED***", line)


def _java_files(root: Path):
    for p in list(root.rglob("*.java")) + list(root.rglob("application*.properties")):
        if not IGNORE_DIRS.intersection(p.relative_to(root).parts):
            yield p


def _finding(cwe, rule, sev, rel, lineno, line):
    return {"cwe_id": cwe, "rule_id": rule, "severity": sev, "file_path": rel.replace("\\", "/"),
            "line_number": lineno, "snippet": redact(line), "line_hash": line_hash(line)}


def builtin_scan(root: Path) -> list[dict]:
    out = []
    for f in _java_files(root):
        rel = str(f.relative_to(root))
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        unprotected = sum(1 for j, l in enumerate(lines) if MAPPING_RE.search(l) and not l.startswith("@")
                          and not _annotated(lines, j))
        for i, line in enumerate(lines, 1):
            if f.suffix == ".properties":
                if PROP_SECRET_RE.match(line):
                    out.append(_finding("CWE-798", "lg-config-secret", "High", rel, i, line))
                continue
            if PLAIN_LOOKUP_RE.search(line):
                out.append(_finding("CWE-916", "lg-plaintext-password-lookup", "High", rel, i, line))
            if CLASS_MAPPING_RE.match(line) and unprotected and not _annotated(lines, i - 1) and "Controller" in f.name:
                out.append(_finding("CWE-862", "lg-controller-no-authz", "Medium", rel, i, line))
            cm = CRED_RE.search(line)
            if cm and not looks_like_label(cm.group(2)):
                out.append(_finding("CWE-798", "lg-hardcoded-credential", "High", rel, i, line))
            if WEAK_PW_RE.search(line):
                out.append(_finding("CWE-916", "lg-weak-password-storage", "Medium", rel, i, line))
            if SQLI_RE.search(line):
                out.append(_finding("CWE-89", "lg-sql-injection", "High", rel, i, line))
            m = MAPPING_RE.search(line)
            if m and SENSITIVE_PATH_RE.search(m.group(1)) and not _annotated(lines, i - 1):
                out.append(_finding("CWE-862", "lg-missing-authz", "Medium", rel, i, line))
    return out


def _annotated(lines: list[str], idx: int) -> bool:
    """Is there an authz annotation in the contiguous annotation block around the mapping line?"""
    j = idx
    while j >= 0 and lines[j].strip().startswith("@"):
        if AUTHZ_RE.search(lines[j]):
            return True
        j -= 1
    j = idx + 1
    while j < len(lines) and lines[j].strip().startswith("@"):
        if AUTHZ_RE.search(lines[j]):
            return True
        j += 1
    return False


def semgrep_scan(root: Path) -> list[dict]:
    exe = shutil.which("semgrep")
    if not exe:
        return []
    proc = subprocess.run([exe, "--config", str(config.RULES_FILE), "--json", "--quiet", str(root)],
                          capture_output=True, text=True, timeout=300)
    try:
        results = json.loads(proc.stdout).get("results", [])
    except json.JSONDecodeError:
        return []
    out = []
    for r in results:
        cwe = (r.get("extra", {}).get("metadata", {}) or {}).get("cwe")
        if not cwe:
            continue
        path = Path(r["path"])
        rel = str(path.relative_to(root)) if path.is_absolute() else str(path)
        lineno = r["start"]["line"]
        line = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()[lineno - 1]
        out.append(_finding(cwe, r["check_id"].split(".")[-1], "High" if cwe in ("CWE-798", "CWE-89") else "Medium",
                            rel, lineno, line))
    return out


def run_static_analysis(root: Path) -> list[dict]:
    seen, merged = set(), []
    for f in builtin_scan(root) + semgrep_scan(root):
        key = (f["cwe_id"], f["file_path"], f["line_number"])
        if key not in seen:
            seen.add(key)
            merged.append(f)
    return sorted(merged, key=lambda f: (f["severity"] != "High", f["file_path"], f["line_number"]))
