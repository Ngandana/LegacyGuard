"""Tests must not depend on the developer's shell (e.g. run.ps1 leaves LEGACYGUARD_BASE_BRANCH=master set)."""
import os

os.environ["LEGACYGUARD_BASE_BRANCH"] = "main"
for _k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "ANTHROPIC_API_KEY", "DATABASE_URL", "LEGACYGUARD_ALLOWED_ROOTS"):
    os.environ.pop(_k, None)
