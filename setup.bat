@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Job Agent - Setup

echo.
echo ========================================
echo   Job Agent - Initial Setup
echo ========================================
echo.

:: -- Step 1: Check Python --
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo.
    echo   Attempting auto-install...
    echo.
    where winget >nul 2>&1
    if errorlevel 1 (
        echo   winget is not available. Please install Python manually:
        echo   https://www.python.org/downloads/
        echo   * Make sure to check "Add Python to PATH"
        echo.
        pause
        exit /b 1
    )
    echo   Installing Python 3.12 via winget...
    winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo   [ERROR] Install failed. Please install manually:
        echo   https://www.python.org/downloads/
        pause
        exit /b 1
    )
    echo.
    echo   * Please close this window and re-run setup.bat to refresh PATH.
    pause
    exit /b 0
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [1/5] %PYVER% OK

:: -- Step 2: Create venv --
echo.
echo [2/5] Creating virtual environment...
if not exist "venv" (
    python -m venv venv
    if errorlevel 1 (
        echo   [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
    echo   -> venv created
) else (
    echo   -> venv already exists (skip)
)

:: -- Step 3: Install dependencies --
echo.
echo [3/5] Installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet 2>nul
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo   [WARNING] Some packages had issues. Retrying...
    pip install -r requirements.txt
)
echo   -> Dependencies installed

:: -- Step 4: Install Playwright --
echo.
echo [4/5] Installing Playwright browser (this may take a while)...
python -m playwright install chromium
if errorlevel 1 (
    echo   [WARNING] Playwright Chromium install had issues. Retrying...
    python -m playwright install chromium
)
echo   -> Chromium installed

:: -- Step 5: Setup .env --
echo.
echo [5/5] Environment config...
if not exist ".env" (
    copy .env.example .env >nul 2>&1
    if not exist ".env" (
        :: PowerShell fallback
        powershell -Command "Copy-Item '.env.example' '.env'"
    )
    echo   -> .env file created.
    echo.
    echo ========================================
    echo   IMPORTANT: Edit .env file
    echo   Set DEEPSEEK_API_KEY=sk-xxx...
    echo ========================================
    echo.
    set /p "DSKEY=Enter DeepSeek API Key (or edit .env later): "
    if defined DSKEY (
        powershell -Command "(Get-Content '.env') -replace 'DEEPSEEK_API_KEY=$', 'DEEPSEEK_API_KEY=!DSKEY!' | Set-Content '.env' -Encoding UTF8"
        echo   -> API Key saved to .env
    )
) else (
    echo   -> .env already exists (skip)
)

:: Create data directory
if not exist "data" mkdir data

echo.
echo ========================================
echo   Setup complete!
echo.
echo   Run start.bat to launch the app.
echo   Open http://localhost:5000 in browser.
echo ========================================
echo.
pause
