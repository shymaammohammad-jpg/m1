@echo off
chcp 65001 >nul
setlocal
set "MAQAD_PHP=%~dp0..\..\php\php.exe"
if not exist "%MAQAD_PHP%" set "MAQAD_PHP=php"
"%MAQAD_PHP%" "%~dp0check.php"
if errorlevel 1 echo راجع دليل README.md لتفعيل متطلبات PHP.
pause
