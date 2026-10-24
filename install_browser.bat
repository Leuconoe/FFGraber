@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -m pip install -r requirements-playwright.txt
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :error
echo Chromium installation complete.
pause
exit /b 0
:error
echo Installation failed. Check Python and your internet connection.
pause
exit /b 1
