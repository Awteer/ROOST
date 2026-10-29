@echo off
rem ============================================================
rem  20_compare_milp.bat : solve the 346 small instances whose MILP optimum
rem    is known (value map 300 + T_max sweep 46) with ROOST's ALNS and
rem    write the gap to the optimum.
rem  Output: results\compare_milp.csv
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set ITER=2000
set SEEDS=1 2 3
%PY% -u tools\compare_milp.py --results ..\NCR_MILP\results --iterations %ITER% --seeds %SEEDS% --out results\compare_milp.csv
pause
