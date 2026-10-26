@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist ".venv\Scripts\python.exe" (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\benchmark_local_ai.py
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
