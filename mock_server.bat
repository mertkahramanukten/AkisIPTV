@echo off
cd /d "%~dp0"
title Akis IPTV - Sahte Xtream sunucusu
REM Kurulu uygulamayi (veya baska bir oynaticiyi) gercek saglayiciya dokunmadan denemek icin:
REM   Sunucu: http://127.0.0.1:8899   Kullanici: demo   Parola: demo
".venv\Scripts\python.exe" tests\mock_server.py %*
pause
