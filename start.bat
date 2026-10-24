@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" -c "import setuptools; import selenium; import undetected_chromedriver" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)
".venv\Scripts\python.exe" main.py %*
set "FFGRABER_EXIT=%ERRORLEVEL%"
if not "%FFGRABER_EXIT%"=="0" if "%~1"=="" goto :error
exit /b %FFGRABER_EXIT%
:error
echo.
echo FFGraber could not start. Check Python 3.10+, Chrome or Edge, and package installation access.
pause
exit /b 1
