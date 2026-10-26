@echo off
setlocal
cd /d "%~dp0"
title Akis IPTV - GitHub'a gonder
set "OWNER=mertkahramanukten"
set "REPO=AkisIPTV"
set "VER=1.0.0"
set "URL=https://github.com/%OWNER%/%REPO%.git"
echo ==============================================
echo   Akis IPTV - GitHub'a gonderiliyor
echo ==============================================
where git >nul 2>nul
if errorlevel 1 (
  echo [HATA] Git bulunamadi.
  pause
  exit /b 1
)

rem ---- 1) Yerel depo + commit
if not exist ".git" git init -b main
git config user.name >nul 2>nul
if errorlevel 1 git config user.name "Mert Kahraman Ukten"
git config user.email >nul 2>nul
if errorlevel 1 git config user.email "mertkahramanukten@gmail.com"
git add -A
git diff --cached --quiet
if not errorlevel 1 goto :remote
> ".git\AKIS_MSG.txt" echo Akis IPTV %VER% guncellemesi
>> ".git\AKIS_MSG.txt" echo.
>> ".git\AKIS_MSG.txt" echo Co-Authored-By: Claude Opus 5.5 ^<noreply@anthropic.com^>
>> ".git\AKIS_MSG.txt" echo Claude-Session: https://claude.ai/code/session_01SoqP8zVr8soMd7HCYRnEa1
git commit -q -F ".git\AKIS_MSG.txt"
del ".git\AKIS_MSG.txt" >nul 2>nul

:remote
git remote get-url origin >nul 2>nul
if errorlevel 1 git remote add origin %URL%

rem ---- 2) GitHub'da repo var mi? Yoksa olusturma sayfasini ac ve bekle
set "GCM_INTERACTIVE=never"
set "GIT_TERMINAL_PROMPT=0"
git ls-remote %URL% >nul 2>nul
if not errorlevel 1 goto :exists
echo.
echo GitHub'da "%REPO%" reposu henuz yok.
echo Tarayicida olusturma sayfasi aciliyor: sadece "Create repository" ye bas.
echo (README / .gitignore / lisans EKLEME.) Repo olusunca devam edecegim...
start "" "https://github.com/new?name=%REPO%&visibility=public&description=Donmaya%%20karsi%%20korumali%%20Xtream%%20Codes%%20IPTV%%20oynaticisi"
set /a TRIES=0
:wait
ping -n 6 127.0.0.1 >nul
git ls-remote %URL% >nul 2>nul
if not errorlevel 1 goto :exists
set /a TRIES+=1
if %TRIES% GEQ 120 (
  echo [HATA] 10 dakika icinde repo olusmadi.
  goto :err
)
<nul set /p "=."
goto :wait

:exists
set "GCM_INTERACTIVE="
set "GIT_TERMINAL_PROMPT="
echo.
echo Repo hazir. Kod gonderiliyor (Git ilk seferde GitHub girisi isteyebilir)...
git push -u origin main
if errorlevel 1 goto :err
git tag -f v%VER% >nul
git push -f origin v%VER%
if errorlevel 1 goto :err

echo.
echo TAMAM: https://github.com/%OWNER%/%REPO%
echo Surum sayfasi aciliyor: dist klasorundeki AkisIPTV-Setup-%VER%.exe dosyasini
echo sayfaya surukle ve "Publish release" de.
start "" "https://github.com/%OWNER%/%REPO%/releases/new?tag=v%VER%&title=Akis%%20IPTV%%20%VER%"
if exist "dist\AkisIPTV-Setup-%VER%.exe" start "" explorer /select,"%~dp0dist\AkisIPTV-Setup-%VER%.exe"
pause
exit /b 0

:err
echo.
echo [HATA] GitHub'a gonderilemedi. Yukaridaki mesaja bak.
pause
exit /b 1
