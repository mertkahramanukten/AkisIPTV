@echo off
setlocal
cd /d "%~dp0"
title Akis IPTV - Kurulum
echo ==============================================
echo   Akis IPTV kurulumu
echo ==============================================
echo.

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo [HATA] Python bulunamadi. https://www.python.org/downloads/ adresinden
  echo        Python 3.10+ kur ve "Add python.exe to PATH" kutusunu isaretle.
  pause
  exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo [HATA] Python 3.10 veya daha yenisi gerekli.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Sanal ortam olusturuluyor...
  %PY% -m venv .venv
  if errorlevel 1 goto :err
)

echo [2/4] pip guncelleniyor...
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check -q

echo [3/4] Kutuphaneler kuruluyor (PySide6, python-mpv, requests)...
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto :err
".venv\Scripts\python.exe" -m pip install py7zr pytest --disable-pip-version-check -q

echo [4/4] Video motoru (libmpv) indiriliyor...
".venv\Scripts\python.exe" tools\get_libmpv.py
if errorlevel 1 goto :err

echo.
echo ==============================================
echo   Kurulum tamam!
echo   Baslatmak icin: run.bat
echo   Sahte sunucuyla denemek icin: demo.bat
echo ==============================================
pause
exit /b 0

:err
echo.
echo [HATA] Kurulum tamamlanamadi. Yukaridaki mesaja bak.
pause
exit /b 1
