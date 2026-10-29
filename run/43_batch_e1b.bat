@echo off
rem ============================================================
rem  43_batch_e1b.bat : experiment E1b (phase 2 only, 20000 iterations, 60 jobs)
rem    start = E1 phase 1 best (results\20261029_e1\raw), modes m2->m2/m4, m3->m3/m5, seeds 1-3
rem    instances: high seed spread 25.35.2 30.39.2 20.32.3 / small NCR effect 25.35.5 30.39.4
rem  Re-run to resume.  Progress: run\41_progress_e1.bat results\20261029_e1b
rem  Output: results\20261029_e1b\
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set WORKERS=5
%PY% -u tools\batch_e1.py --workers %WORKERS% --t0-factor 0.02 --out results\20261029_e1b --phase2-from results\20261029_e1 --instances 25.35.2.a 30.39.2.a 20.32.3.a 25.35.5.a 30.39.4.a --phase2-iterations 20000
pause
