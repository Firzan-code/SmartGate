@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Lingkungan .venv belum dibuat. Ikuti README.md.
  pause
  exit /b 1
)
"%PYTHON%" run_camera.py --backend dshow %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
