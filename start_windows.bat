@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

if not exist "run.py" goto missing_files
if not exist "backend\app.py" goto missing_files
if not exist ".venv\Scripts\python.exe" goto not_installed
if not exist "frontend\dist\index.html" goto not_installed

echo.
echo Starting Raqib. Keep this window open while using the application.
echo Press Ctrl+C to stop the server.
".venv\Scripts\python.exe" "run.py"
set "RAQIB_EXIT=%ERRORLEVEL%"
if "%RAQIB_EXIT%"=="0" exit /b 0
echo.
echo ERROR: Raqib could not start. Read the message above.
pause
exit /b %RAQIB_EXIT%

:missing_files
echo.
echo ERROR: Extract the entire ZIP first, then run start_windows.bat
echo from its extracted folder. Do not open backend\app.py inside the ZIP.
pause
exit /b 1

:not_installed
echo.
echo ERROR: Run install_windows.bat once before starting the application.
echo This installs dependencies and builds the Arabic interface.
pause
exit /b 1
