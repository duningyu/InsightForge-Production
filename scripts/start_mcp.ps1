$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
if (-not (Test-Path ".venv")) { & $Python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
if ($env:INSIGHTFORGE_SKIP_INSTALL -ne "1") { python -m pip install -e . }
python -m app.mcp_server
