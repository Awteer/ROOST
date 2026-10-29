@echo off
rem ============================================================
rem  46_batch_e1c.bat : experiment E1c (no-loop only, 20000 iterations, 45 jobs)
rem    per instance and seed 1-3:
rem      (4) from the initial solution            20000 it
rem      (2)->(4) warm  from the E1 (2) best      20000 it
rem      (2)->(2) continue from the E1 (2) best   20000 it
rem    instances: high (4) seed spread 25.35.2 30.39.2 20.32.3 / small NCR effect 25.35.5 30.39.1
rem  Re-run to resume.  Progress: run\41_progress_e1.bat results\20261029_e1c
rem  Output: results\20261029_e1c\
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set WORKERS=5
%PY% -u tools\batch_e1.py --workers %WORKERS% --t0-factor 0.02 --out results\20261029_e1c --phase2-from results\20261029_e1 --instances 25.35.2.a 30.39.2.a 20.32.3.a 25.35.5.a 30.39.1.a --phase2-iterations 20000 --pairs 2:2,4 --scratch-modes 4
pause
