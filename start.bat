@echo off
chcp 65001 >nul
title Job Agent

:: Activate venv
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
) else (
    echo [ERROR] venv not found. Run setup.bat first.
    pause
    exit /b 1
)

:: Check .env
if not exist ".env" (
    echo [ERROR] .env not found. Run setup.bat first.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Job Agent starting...
echo ========================================
echo.
echo   Open in browser: http://localhost:5000
echo   Stop: Ctrl+C
echo.

:: Open browser after 2 seconds
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5000"

:: Start the app
python app.py
