@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto run
echo [ERROR] Siapkan .venv sesuai README terlebih dahulu.
pause
exit /b 1
:run
".venv\Scripts\python.exe" -B run_servo_demo.py %*
set "result=%ERRORLEVEL%"
if not "%result%"=="0" pause
exit /b %result%
