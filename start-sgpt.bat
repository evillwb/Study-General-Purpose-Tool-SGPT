@echo off
rem SGPT launcher for Windows: double-click to start the app.
cd /d "%~dp0"
if not exist .venv (
  echo First run: setting up SGPT. This takes a few minutes...
  python -m venv .venv || (echo Python 3.10+ is required: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip >nul
  .venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
)
.venv\Scripts\python -m sgpt.app %*
pause
