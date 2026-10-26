@echo off
setlocal
cd /d "%~dp0"
title Akis IPTV - GitHub'a gonder
set "OWNER=mertkahramanukten"
set "REPO=AkisIPTV"
set "VER=1.0.0"
echo ==============================================
echo   Akis IPTV - GitHub'a gonderiliyor
echo ==============================================
echo ONCE: GitHub'da bos bir "%REPO%" reposu olusturulmus olmali
echo       (https://github.com/new  -  README ekleme).
echo.
where git >nul 2>nul
if errorlevel 1 (
  echo [HATA] Git bulunamadi.
  pause
  exit /b 1
)
if not exist ".git" git init -b main
git config user.name >nul 2>nul
if errorlevel 1 git config user.name "Mert Kahraman Ukten"
git config user.email >nul 2>nul
if errorlevel 1 git config user.email "mertkahramanukten@gmail.com"

git add -A
> ".git\AKIS_MSG.txt" echo Akis IPTV %VER%
>> ".git\AKIS_MSG.txt" echo.
>> ".git\AKIS_MSG.txt" echo Donmaya karsi korumali Xtream Codes IPTV oynaticisi: Canli TV, film, dizi, EPG.
>> ".git\AKIS_MSG.txt" echo Tek dosyalik Windows kurulumu (PyInstaller + Inno Setup) dahil.
>> ".git\AKIS_MSG.txt" echo.
>> ".git\AKIS_MSG.txt" echo Co-Authored-By: Claude Opus 5.5 ^<noreply@anthropic.com^>
>> ".git\AKIS_MSG.txt" echo Claude-Session: https://claude.ai/code/session_01SoqP8zVr8soMd7HCYRnEa1
git diff --cached --quiet
if errorlevel 1 git commit -q -F ".git\AKIS_MSG.txt"
del ".git\AKIS_MSG.txt" >nul 2>nul

git remote get-url origin >nul 2>nul
if errorlevel 1 git remote add origin https://github.com/%OWNER%/%REPO%.git
echo.
echo Gonderiliyor (Git ilk seferde GitHub girisi isteyebilir)...
git push -u origin main
if errorlevel 1 goto :err
git tag -f v%VER% >nul
git push -f origin v%VER%
if errorlevel 1 goto :err

echo.
echo Kod GitHub'da. Simdi surum sayfasi aciliyor:
echo   dist klasorundeki AkisIPTV-Setup-%VER%.exe dosyasini sayfaya surukle, "Publish release" de.
start "" "https://github.com/%OWNER%/%REPO%/releases/new?tag=v%VER%&title=Akis%%20IPTV%%20%VER%"
if exist "dist\AkisIPTV-Setup-%VER%.exe" start "" explorer /select,"%~dp0dist\AkisIPTV-Setup-%VER%.exe"
pause
exit /b 0

:err
echo.
echo [HATA] GitHub'a gonderilemedi. Repo olusturuldu mu, giris yapildi mi?
pause
exit /b 1
