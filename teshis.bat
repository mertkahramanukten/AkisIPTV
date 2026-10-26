@echo off
cd /d "%~dp0"
echo Akis IPTV - yayin teshisi calisiyor (1-2 dakika surer)...
echo Kullanici adi ve parola rapora yazilmaz.
echo.
".venv\Scripts\python.exe" tools\teshis.py %*
echo.
echo Rapor: %~dp0teshis_raporu.txt
timeout /t 8 >nul
