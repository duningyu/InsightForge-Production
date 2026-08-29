param(
    [Parameter(Mandatory=$true)][string]$PackagePath,
    [string]$ExpectedSha256 = "",
    [string]$TargetDir = "E:\AI_Projects\InsightForge",
    [switch]$ForceStopTargetProcesses
)

$ErrorActionPreference = "Stop"
$TargetDir = [System.IO.Path]::GetFullPath($TargetDir)
$ParentDir = Split-Path -Parent $TargetDir
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$StagingBase = Join-Path $ParentDir ("InsightForge.staging." + $Stamp)
$BackupDir = Join-Path $ParentDir ("InsightForge.backup." + $Stamp)
$FailedDir = Join-Path $ParentDir ("InsightForge.failed." + $Stamp)
$CheckVenv = Join-Path $ParentDir ("InsightForge.verifyvenv." + $Stamp)
$ReportPath = Join-Path $ParentDir ("InsightForge.deploy." + $Stamp + ".json")

function Write-Status([string]$Message) {
    Write-Host ("[InsightForge deploy] " + $Message)
}

function Get-TargetProcesses {
    if (-not (Test-Path $TargetDir)) { return @() }
    return @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -and $_.CommandLine.Contains($TargetDir, [System.StringComparison]::OrdinalIgnoreCase)
    })
}

function Stop-TargetProcessesIfAllowed {
    $processes = @(Get-TargetProcesses)
    if ($processes.Count -eq 0) { return }
    if (-not $ForceStopTargetProcesses) {
        $processes | Select-Object ProcessId,Name,CommandLine | Format-Table -AutoSize
        throw "Processes are using the formal InsightForge directory. Re-run with -ForceStopTargetProcesses only after reviewing the list above."
    }
    foreach ($process in $processes) {
        Write-Status ("Stopping target process PID=" + $process.ProcessId + " Name=" + $process.Name)
        Stop-Process -Id $process.ProcessId -Force
    }
}

function Invoke-AppChecks([string]$Root, [string]$PythonExe) {
    Push-Location $Root
    try {
        & $PythonExe -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw "pytest failed" }
        & $PythonExe -m compileall -q app tests
        if ($LASTEXITCODE -ne 0) { throw "compileall failed" }
        & $PythonExe -c "from app.__main__ import _load_local_env; from pathlib import Path; _load_local_env(Path('.env')); from app.config import Settings; from app.db import Database; s=Settings.from_env(); db=Database(s.database_path); db.init_schema(); import sqlite3; c=sqlite3.connect(db.path); print('integrity=' + str(c.execute('PRAGMA integrity_check').fetchone()[0])); print('foreign_keys=' + str(len(c.execute('PRAGMA foreign_key_check').fetchall()))); c.close()"
        if ($LASTEXITCODE -ne 0) { throw "database migration/integrity check failed" }
    }
    finally { Pop-Location }
}

function Invoke-HealthSmoke([string]$Root, [string]$PythonExe, [int]$Port) {
    Push-Location $Root
    $process = $null
    try {
        $process = Start-Process -FilePath $PythonExe -ArgumentList @("-m","uvicorn","app.main:app","--host","127.0.0.1","--port",$Port) -PassThru -WindowStyle Hidden
        $ready = $false
        for ($i=0; $i -lt 60; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $health = Invoke-RestMethod -Uri ("http://127.0.0.1:" + $Port + "/api/health") -TimeoutSec 2
                if ($health.status -eq "ok") { $ready = $true; break }
            } catch {}
        }
        if (-not $ready) { throw "health smoke failed" }
        Write-Status ("health smoke passed on port " + $Port)
    }
    finally {
        if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $PackagePath)) { throw "Package not found: $PackagePath" }
New-Item -ItemType Directory -Force -Path $ParentDir | Out-Null
$ActualSha = (Get-FileHash -LiteralPath $PackagePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ExpectedSha256 -and $ActualSha -ne $ExpectedSha256.ToLowerInvariant()) {
    throw "Package SHA-256 mismatch. Expected=$ExpectedSha256 Actual=$ActualSha"
}
Write-Status ("package SHA-256=" + $ActualSha)

Stop-TargetProcessesIfAllowed
if (Test-Path $StagingBase) { Remove-Item $StagingBase -Recurse -Force }
Expand-Archive -LiteralPath $PackagePath -DestinationPath $StagingBase -Force
$StageRoot = if (Test-Path (Join-Path $StagingBase "InsightForge\app")) { Join-Path $StagingBase "InsightForge" } else { $StagingBase }
if (-not (Test-Path (Join-Path $StageRoot "app\main.py"))) { throw "Package does not contain an InsightForge application root" }

# Preserve mutable local data/config before staging verification.
if (Test-Path $TargetDir) {
    foreach ($name in @(".env","data","runtime","instance")) {
        $source = Join-Path $TargetDir $name
        if (Test-Path $source) {
            $destination = Join-Path $StageRoot $name
            if (Test-Path $destination) { Remove-Item $destination -Recurse -Force }
            Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
        }
    }
}

Write-Status "creating isolated staging verification environment"
py -3.12 -m venv $CheckVenv
$CheckPython = Join-Path $CheckVenv "Scripts\python.exe"
& $CheckPython -m pip install --disable-pip-version-check -r (Join-Path $StageRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "dependency installation failed in staging" }
& $CheckPython -m pip install --disable-pip-version-check "pytest>=8,<10"
if ($LASTEXITCODE -ne 0) { throw "pytest installation failed in staging" }
Invoke-AppChecks $StageRoot $CheckPython
Invoke-HealthSmoke $StageRoot $CheckPython 8898

$Switched = $false
try {
    if (Test-Path $TargetDir) {
        Move-Item -LiteralPath $TargetDir -Destination $BackupDir
        Write-Status ("backup created: " + $BackupDir)
    }
    Move-Item -LiteralPath $StageRoot -Destination $TargetDir
    $Switched = $true

    $TargetVenv = Join-Path $TargetDir ".venv"
    py -3.12 -m venv $TargetVenv
    $TargetPython = Join-Path $TargetVenv "Scripts\python.exe"
    & $TargetPython -m pip install --disable-pip-version-check -r (Join-Path $TargetDir "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "formal dependency installation failed" }
    & $TargetPython -m pip install --disable-pip-version-check "pytest>=8,<10"
    if ($LASTEXITCODE -ne 0) { throw "formal pytest installation failed" }
    Invoke-AppChecks $TargetDir $TargetPython
    Invoke-HealthSmoke $TargetDir $TargetPython 8899

    $report = [ordered]@{
        status = "PASS"
        package_sha256 = $ActualSha
        target_directory = $TargetDir
        backup_directory = $(if (Test-Path $BackupDir) { $BackupDir } else { $null })
        staging_verified = $true
        formal_verified = $true
        rollback_available = $(Test-Path $BackupDir)
        generated_at = (Get-Date).ToString("o")
    }
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    Write-Status ("deployment completed; report=" + $ReportPath)
}
catch {
    Write-Status ("deployment failed: " + $_.Exception.Message)
    if ($Switched -and (Test-Path $TargetDir)) {
        Move-Item -LiteralPath $TargetDir -Destination $FailedDir
    }
    if (Test-Path $BackupDir) {
        Move-Item -LiteralPath $BackupDir -Destination $TargetDir
        Write-Status "rollback restored previous formal directory"
    }
    throw
}
finally {
    if (Test-Path $CheckVenv) { Remove-Item $CheckVenv -Recurse -Force }
    if (Test-Path $StagingBase) { Remove-Item $StagingBase -Recurse -Force }
}
