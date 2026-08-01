@echo off
REM Sentinel AI one-time setup. Run this once before using start.bat.
REM Requires: Python 3.10+ on PATH, and (for face_recognition) either
REM   (a) dlib-bin already working, or
REM   (b) VS Build Tools with "Desktop development with C++" installed.

cd /d "%~dp0"

echo === Step 1: Creating virtual environment ===
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Failed to create venv. Is Python installed and on PATH?
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo.
echo === Step 2: Upgrading pip ===
python -m pip install --upgrade pip

echo.
echo === Step 3: Installing dependencies ===
echo Trying precompiled dlib first (fast, no compiler needed)...
pip install dlib-bin
if errorlevel 1 (
    echo dlib-bin unavailable for this Python version — falling back to
    echo compiling dlib from source. This can take 5-15+ minutes.
    pip install dlib
)

pip install -r requirements.txt

echo.
echo === Step 4: Verifying core logic offline ===
python tests\manual_verify.py
if errorlevel 1 (
    echo.
    echo [WARNING] Offline verification reported a failure above.
    echo Review the [FAIL] lines before proceeding.
    pause
    exit /b 1
)

echo.
echo === Setup complete ===
echo.
echo IMPORTANT: This app uses a local LLM via Ollama - no API keys needed.
echo If you haven't already:
echo   1. Install Ollama from https://ollama.com
echo   2. Run: ollama pull llama3.2:3b
echo   3. Run: ollama pull moondream
echo.
echo Run start.bat to launch the app.
pause
