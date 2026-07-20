@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtuelle Umgebung fehlt. Bitte zuerst installieren:
  echo   py -3.12 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "app\main.py"
set EXIT_CODE=%ERRORLEVEL%

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Die Anwendung wurde mit Fehlercode %EXIT_CODE% beendet.
  pause
)

exit /b %EXIT_CODE%
