@echo off
rem ============================================================
rem  54_analysis_e2_seed3.bat : the same tables for seed 3 (verification data)
rem    Run this ONLY after the hypotheses from seeds 1-2 are written down.
rem    -> results\20261105_e2\analysis_s3\
rem  Reads raw\ and stages\ only.
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set PYTHONDONTWRITEBYTECODE=1
set OUT=results\20261105_e2
echo This shows seed 3 (held-out data). Close this window now if the hypotheses are not written yet.
pause
%PY% -u tools\e2_tables.py --out %OUT% --seeds 3 || goto :err
%PY% -u tools\e2_ncr_valley.py --out %OUT% --seeds 3 || goto :err
echo.
echo done. tables: %OUT%\analysis_s3
pause
exit /b 0
:err
echo.
echo ERROR: a step failed (see the message above).
pause
exit /b 1
