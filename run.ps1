# Starts LegacyGuard against the cloned African Arts & Craft repo.
# Optional free LLM (see README): set these BEFORE running, e.g.
#   $env:LLM_BASE_URL="http://localhost:11434/v1"; $env:LLM_MODEL="qwen2.5-coder:7b"
$root = $PSScriptRoot
$env:LEGACYGUARD_BASE_BRANCH = "master"
$env:LEGACYGUARD_ALLOWED_ROOTS = "$root"
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\frontend'; npm run dev"
cd "$root\backend"
Write-Host "Dashboard: http://localhost:5173   Target path to paste: $root\targets\african-arts-craft"
try { .\.venv\Scripts\python -m uvicorn app.main:app --port 8000 }
finally {  # do not leave settings behind in the caller's shell (they break pytest)
    Remove-Item Env:LEGACYGUARD_BASE_BRANCH, Env:LEGACYGUARD_ALLOWED_ROOTS -ErrorAction SilentlyContinue
    Set-Location $root
}
