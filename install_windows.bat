@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PIP_CACHE_DIR=%CD%\.cache\pip"
set "npm_config_cache=%CD%\.cache\npm"

echo.
echo Raqib - Windows installation

echo Extract the entire ZIP before running this file.
if not exist "run.py" goto missing_files
if not exist "backend\app.py" goto missing_files
if not exist "backend\requirements.lock" goto missing_files
if not exist "frontend\package-lock.json" goto missing_files
if not exist "scripts\sync_references.py" goto missing_files

where node >nul 2>&1
if errorlevel 1 goto missing_node
where npm >nul 2>&1
if errorlevel 1 goto missing_node
node -e "const v=process.versions.node.split('.').map(Number);process.exit(v[0] > 20 || (v[0] === 20 && v[1] >= 19) ? 0 : 1)"
if errorlevel 1 goto missing_node

if exist ".venv\Scripts\python.exe" goto check_venv
if exist ".venv" goto incompatible_venv
call :find_python
if errorlevel 1 goto missing_python
echo Creating the project Python environment...
%PYTHON_LAUNCHER% -m venv ".venv"
if errorlevel 1 goto install_failed

:check_venv
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] < (3,15) else 1)"
if errorlevel 1 goto incompatible_venv

echo.
echo [1/5] Installing Python dependencies...
".venv\Scripts\python.exe" -m pip install -r "backend\requirements.lock"
if errorlevel 1 goto install_failed

echo.
echo [2/5] Installing Chromium for PDF reports...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto install_failed

echo.
echo [3/5] Building the Arabic application interface...
pushd "frontend"
call npm ci --no-audit --no-fund
if errorlevel 1 goto frontend_failed
call npm run build
if errorlevel 1 goto frontend_failed
popd

echo.
echo [4/5] Checking the application setup...
".venv\Scripts\python.exe" "run.py" --check
if errorlevel 1 goto install_failed

echo.
echo [5/5] Downloading verified public Ministry references...
".venv\Scripts\python.exe" "scripts\sync_references.py"
if errorlevel 1 goto references_failed

echo.
echo Installation completed. Double-click start_windows.bat to open Raqib.
echo Original user PDFs are imported separately from the reference library.
pause
exit /b 0

:find_python
where py >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 -c "import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>&1
if errorlevel 1 goto try_py_latest
set "PYTHON_LAUNCHER=py -3.12"
exit /b 0
:try_py_latest
py -3 -c "import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>&1
if errorlevel 1 goto try_python
set "PYTHON_LAUNCHER=py -3"
exit /b 0
:try_python
where python >nul 2>&1
if errorlevel 1 exit /b 1
python -c "import sys; sys.exit(0 if (3,12) <= sys.version_info[:2] < (3,15) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PYTHON_LAUNCHER=python"
exit /b 0

:missing_files
echo.
echo ERROR: The full project was not found beside this installer.
echo Right-click m1-main.zip, choose Extract All, then run this file
echo from the extracted folder, not from inside the ZIP or its Temp view.
pause
exit /b 1

:missing_python
echo.
echo ERROR: Install Python 3.12, 3.13 or 3.14 from:
echo https://www.python.org/downloads/windows/
echo Enable the Python launcher or Add python.exe to PATH, then retry.
pause
exit /b 1

:missing_node
echo.
echo ERROR: Install Node.js LTS, version 20.19 or newer, from:
echo https://nodejs.org/
echo Close this window and run install_windows.bat again after installation.
pause
exit /b 1

:incompatible_venv
echo.
echo ERROR: The existing .venv is not a usable Windows Python 3.12-3.14 environment.
echo Preserve your data folder. Rename only .venv, then run this installer again.
echo No existing environment or audit data was removed.
pause
exit /b 1

:frontend_failed
set "INSTALL_EXIT=%ERRORLEVEL%"
popd
echo.
echo ERROR: Frontend installation failed. Check the message above and retry.
pause
exit /b %INSTALL_EXIT%

:references_failed
set "INSTALL_EXIT=%ERRORLEVEL%"
echo.
echo ERROR: Public references could not be downloaded or verified.
echo The application is installed. You can use start_windows.bat and import
echo official references manually, or retry from this project folder with:
echo .venv\Scripts\python.exe scripts\sync_references.py
echo TLS and checksum verification remain enabled.
pause
exit /b %INSTALL_EXIT%

:install_failed
set "INSTALL_EXIT=%ERRORLEVEL%"
echo.
echo ERROR: Installation stopped. Check the message above, correct the issue,
echo and run install_windows.bat again. Existing audit data is preserved.
pause
exit /b %INSTALL_EXIT%
