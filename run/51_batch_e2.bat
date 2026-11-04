@echo off
rem ============================================================
rem  51_batch_e2.bat : E2 main (slope-city stage), 5000 iterations, 5760 jobs (about 85 h)
rem    10 layouts (n=20,25 x m=1..5) x 4 terrains x 2 batteries x seeds 1-3 x 24 runs (Tmax 1.0 .975 .95 .925 .9 .875 .85 .8)
rem    order: all of seed 1 -> seed 2 -> seed 3
rem  Re-run to resume.  Progress: run\52_progress_e2.bat results\20261105_e2
rem  Output: results\20261105_e2\
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set WORKERS=5
%PY% -u tools\batch_e2.py --workers %WORKERS% --iterations 5000 --out results\20261105_e2
pause
