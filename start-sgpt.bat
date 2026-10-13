@echo off
rem SGPT launcher for Windows: double-click to start the app.
rem (Prefer SGPT.exe from the Releases page if you don't want to install Python.)
setlocal
cd /d "%~dp0"

if not exist "sgpt\app.py" goto :not_unzipped
if exist ".venv\Scripts\python.exe" goto :run

rem A .venv folder without python.exe is left over from a setup that stopped. Start again.
if exist ".venv" rmdir /s /q ".venv"

echo First run: setting up SGPT. This takes a few minutes...
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :no_python

%PY% -m venv .venv
if not exist ".venv\Scripts\python.exe" goto :no_python

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :install_failed

:run
".venv\Scripts\python.exe" -m sgpt.app %*
pause
exit /b 0

:not_unzipped
echo Can't find the SGPT files next to this launcher.
echo If you opened the ZIP download, extract it first (right-click the ZIP, Extract All),
echo then double-click start-sgpt.bat inside the extracted folder.
pause
exit /b 1

:no_python
if exist ".venv" rmdir /s /q ".venv"
echo Python 3.10 or newer is needed: https://www.python.org/downloads/
echo When installing, tick "Add python.exe to PATH". Then run this launcher again.
echo (Or use SGPT.exe, which needs no Python.)
pause
exit /b 1

:install_failed
echo Installing the packages failed. Check your internet connection and run this again.
echo If it keeps failing, delete the .venv folder and try once more.
pause
exit /b 1
