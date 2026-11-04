@echo off
rem ============================================================
rem  52_progress_e2.bat : show E2 progress (refresh every 60 s, Ctrl+C to quit)
rem  Usage: 52_progress_e2.bat [results folder]  (default results\20261105_e2)
rem  Read-only.
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set OUT=%~1
if "%OUT%"=="" set OUT=results\20261105_e2
%PY% tools\e1_progress.py --out %OUT% --watch 60
pause
