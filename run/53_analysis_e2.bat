@echo off
rem ============================================================
rem  53_analysis_e2.bat : E2 analysis material for seeds 1-2 (seed 3 is held out)
rem    1) git pull (slope-city)
rem    2) tables  -> results\20261105_e2\analysis_s12\  (E2_jobs_s12.csv, E2_ncr_value_s12.csv, E2_ncr_value_summary_s12.csv)
rem    3) valley  -> results\20261105_e2\analysis_s12\  (E2_ncr_valley_s12.csv/.png, E2_ncr_candidates_s12.csv)
rem    4) sheets C and A -> results\20261105_e2\figs\
rem  Reads raw\ and stages\ only. Does not change or delete existing files.
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
git pull --ff-only
call "%~dp0_python.bat"
set PYTHONDONTWRITEBYTECODE=1
set OUT=results\20261105_e2
%PY% -u tools\e2_tables.py --out %OUT% --seeds 1 2 || goto :err
%PY% -u tools\e2_ncr_valley.py --out %OUT% --seeds 1 2 || goto :err
%PY% -u tools\plot_e2_sheets.py --out %OUT% --sheets C A --seeds 1 2 || goto :err
echo.
echo done. tables: %OUT%\analysis_s12   figures: %OUT%\figs
pause
exit /b 0
:err
echo.
echo ERROR: a step failed (see the message above).
pause
exit /b 1
