@echo off
rem ============================================================
rem  40_batch_e1.bat : experiment E1 (387 jobs, parallel, resumable)
rem    n = 20/25/30, m = 1..5, modes 1-5, seeds 1-3, 5000 iterations
rem    phase 2 = warm start from the no-NCR best (m2->m2/m4, m3->m3/m5)
rem    convergence = n30 m1-3: modes 2/5 and m3->m3/m5, 20000 iterations
rem  Re-run the same command to resume (finished jobs are skipped).
rem  Output: results\20261029_e1\ (progress.log, jobs.json, raw\summary.csv at the end)
rem  Progress: run\41_progress_e1.bat
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set WORKERS=5
set T0=0.02
%PY% -u tools\batch_e1.py --workers %WORKERS% --t0-factor %T0% --out results\20261029_e1
pause
