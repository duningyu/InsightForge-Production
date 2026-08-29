@echo off
setlocal
cd /d "%~dp0"

set "IF_PYTHON=%INSIGHTFORGE_PYTHON%"
if not defined IF_PYTHON (
    if not exist ".venv\Scripts\python.exe" (
        where py >nul 2>nul
        if errorlevel 1 (
            python -m venv ".venv"
        ) else (
            py -3 -m venv ".venv"
        )
        if errorlevel 1 (
            echo [InsightForge] Failed to create the local Python environment.
            exit /b 1
        )
    )
    set "IF_PYTHON=%CD%\.venv\Scripts\python.exe"
)

if /I not "%INSIGHTFORGE_SKIP_INSTALL%"=="1" (
    "%IF_PYTHON%" -m pip install --disable-pip-version-check --upgrade -e .
    if errorlevel 1 (
        echo [InsightForge] Configured package index failed; retrying the official Python index.
        "%IF_PYTHON%" -m pip install --disable-pip-version-check --index-url https://pypi.org/simple --upgrade -e .
        if errorlevel 1 (
            echo [InsightForge] Dependency installation failed.
            exit /b 1
        )
    )
)

"%IF_PYTHON%" -m app.runtime_check
if errorlevel 1 exit /b 1
if /I "%INSIGHTFORGE_VERIFY_ONLY%"=="1" exit /b 0

if not defined HOST set "HOST=127.0.0.1"
if not defined PORT set "PORT=8001"
echo [InsightForge] Starting local server.
"%IF_PYTHON%" -m app
