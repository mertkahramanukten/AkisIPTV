@echo off
setlocal
cd /d "%~dp0"
title Akis IPTV - Kurulum dosyasi hazirlaniyor
echo ==============================================
echo   Akis IPTV - tek dosyalik kurulum (Setup.exe)
echo ==============================================
if not exist ".venv\Scripts\python.exe" (
  echo Gelistirme ortami yok, once setup.bat calistiriliyor...
  call setup.bat
)
if not exist ".venv\Scripts\python.exe" goto :err
".venv\Scripts\python.exe" tools\build_installer.py
if errorlevel 1 goto :err
echo.
echo Kurulum dosyasi dist klasorunde. Klasor aciliyor...
start "" explorer "%~dp0dist"
pause
exit /b 0

:err
echo.
echo [HATA] Kurulum dosyasi olusturulamadi. Yukaridaki mesaja bak.
pause
exit /b 1
