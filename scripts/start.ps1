$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }
if (-not (Test-Path ".venv")) { & $Python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
if ($env:INSIGHTFORGE_SKIP_INSTALL -ne "1") { python -m pip install -e . }
$HostValue = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$PortValue = if ($env:PORT) { $env:PORT } else { "8000" }
python -m uvicorn app.main:app --host $HostValue --port $PortValue
