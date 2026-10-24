@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
echo.
echo Raqib - one-time LOCAL AI setup for an 8 GB computer
echo Model downloads require Internet during setup; contract processing is local.
echo.
if not exist ".venv\Scripts\python.exe" goto missing_environment
if not exist "scripts\setup_local_ai.py" goto missing_files
".venv\Scripts\python.exe" "scripts\setup_local_ai.py"
set "SETUP_RESULT=%ERRORLEVEL%"
echo.
if "%SETUP_RESULT%"=="0" echo Local AI and Arabic OCR are ready. Open start_windows.bat.
if "%SETUP_RESULT%"=="2" echo The local model is ready. Finish the OCR setup described above for scanned files.
if "%SETUP_RESULT%"=="3" echo Install Ollama from the official page, then run this file again.
pause
exit /b %SETUP_RESULT%
:missing_environment
echo Run install_windows.bat first, then run this local AI setup again.
pause
exit /b 1
:missing_files
echo Extract the entire ZIP to a normal folder first. Do not run from inside ZIP.
pause
exit /b 1
