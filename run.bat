@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Once setup.bat dosyasini calistir.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" run_akis.py %*
