@echo off
rem ============================================================
rem  42_plot_e1.bat : draw the routes of all E1 results as PNG
rem    results\20261029_e1\png\<instance>_s<seed>.png  (9 maps: modes 1-5 and phase 2)
rem    results\20261029_e1\png\<instance>_long.png     (20000-iteration runs, n30 m1-3)
rem  Existing PNGs are skipped.  Set FORCE=--force to redraw all.
rem  Draw one instance only: set ONLY=--only 30-39-2-a
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set WORKERS=4
set FORCE=
set ONLY=
%PY% -u tools\plot_e1.py --out results\20261029_e1 --workers %WORKERS% %FORCE% %ONLY%
pause
