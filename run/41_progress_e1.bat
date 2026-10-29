@echo off
rem ============================================================
rem  41_progress_e1.bat : show E1 progress (refresh every 60 s, Ctrl+C to quit)
rem  Read-only.  Safe to open any number of times while 40_batch_e1.bat runs.
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
%PY% tools\e1_progress.py --out results\20261029_e1 --watch 60
pause
