@echo off
rem ============================================================
rem  50_pilot_e2.bat : E2 pilot (slope-city stage), 1000 iterations
rem    layouts 20.1 25.1 x terrains flat/slope/undul/atami x batteries b150/b030 x seed 1
rem    x 14 runs = 224 jobs.  Purpose: check it runs on this PC and measure time per job.
rem  Re-run to resume.  Progress: run\52_progress_e2.bat results\20261104_e2pilot
rem  Output: results\20261104_e2pilot\
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set WORKERS=5
%PY% -u tools\batch_e2.py --workers %WORKERS% --iterations 1000 --out results\20261104_e2pilot --layouts 20.1 25.1 --seeds 1
pause
