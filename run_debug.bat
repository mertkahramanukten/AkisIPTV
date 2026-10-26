@echo off
cd /d "%~dp0"
REM Konsol penceresiyle calistirir; loglar hem burada hem data\logs\akis.log icinde gorunur.
".venv\Scripts\python.exe" run_akis.py %*
pause
