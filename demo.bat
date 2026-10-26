@echo off
cd /d "%~dp0"
REM Sahte Xtream sunucusunu (127.0.0.1:8899, demo/demo) uygulamanin icinde baslatir.
REM "Test: Sorunlu Kanallar" kategorisi kopma/donma/404 senaryolarini taklit eder.
REM Konsol penceresinde canli loglari gorursun.
if not exist ".venv\Scripts\python.exe" (
  echo Once setup.bat dosyasini calistir.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run_akis.py --demo
echo.
echo Uygulama kapandi.
pause
