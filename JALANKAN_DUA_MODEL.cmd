@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Lingkungan .venv belum dibuat. Ikuti bagian Persiapan Python di README.md.
  echo py -3.11 -m venv .venv
  echo .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
echo Dashboard: http://127.0.0.1:5000
echo Ctrl+C untuk berhenti. Python tidak membuka port serial.
"%PYTHON%" run_dashboard.py %*
set "RESULT=%ERRORLEVEL%"
echo Server berhenti dengan kode %RESULT%.
pause
exit /b %RESULT%
