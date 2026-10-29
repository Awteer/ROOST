@echo off
rem ============================================================
rem  45_plot_e1_noloop.bat : no-loop comparison PNGs for E1, one per instance
rem    rows = seed 1-3, columns = (2) no NCR / (4) NCR / (2)->(4) warm, plus best-value history
rem  Output: results\20261029_e1\png\noloop\<instance>.png  (15 files)
rem  Existing PNGs are skipped.  Set FORCE=--force to redraw all.
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set WORKERS=4
set FORCE=
%PY% -u tools\plot_e1.py --out results\20261029_e1 --workers %WORKERS% --noloop %FORCE%
pause
