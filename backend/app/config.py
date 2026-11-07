"""Runtime configuration (env-driven). See README for the full list."""
import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///legacyguard.db")  # use postgresql+psycopg://... in prod
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("LEGACYGUARD_MODEL", "claude-sonnet-5-5")
MAX_ATTEMPTS = 3  # REQ-008: bounded automated retries, then escalate to a human
BASE_BRANCH = os.getenv("LEGACYGUARD_BASE_BRANCH", "main")

# Module 1 "validates target scope": scans are only allowed under these roots (NFR-001).
ALLOWED_ROOTS = [
    Path(p).resolve()
    for p in os.getenv("LEGACYGUARD_ALLOWED_ROOTS", str(Path(__file__).resolve().parents[2])).split(os.pathsep)
    if p
]
RULES_FILE = Path(__file__).resolve().parents[1] / "rules" / "legacyguard.yml"

# LLM provider: "anthropic" (paid API) or "openai" = any OpenAI-compatible endpoint (Ollama, Groq, Gemini: free options).
LLM_PROVIDER = os.getenv("LEGACYGUARD_LLM", "openai" if os.getenv("LLM_BASE_URL") else "anthropic")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")          # e.g. http://localhost:11434/v1 (Ollama)
LLM_API_KEY = os.getenv("LLM_API_KEY", "ollama")      # Ollama ignores it; Groq/Gemini need a real free key
LLM_MODEL = os.getenv("LLM_MODEL", "")                # e.g. qwen2.5-coder:7b
