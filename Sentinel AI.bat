@echo off
REM Sentinel AI launcher — double-click this to start the app.
REM Assumes setup.bat (or manual setup) has already been run once.

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo [ERROR] Virtual environment not found at .venv
    echo Run setup.bat first, or create it manually:
    echo     python -m venv .venv
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo Starting Sentinel AI...
echo This will open http://127.0.0.1:8000 in your browser.
echo Press Ctrl+C in this window to stop the app.
echo.

python run.py

pause
