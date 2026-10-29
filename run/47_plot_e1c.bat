@echo off
rem ============================================================
rem  47_plot_e1c.bat : E1c route PNGs, one per instance
rem    rows = seed 1-3, columns = (2)->(2) continue / (4) from initial / (2)->(4) warm, plus history
rem  Output: results\20261029_e1c\png\<instance>.png
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
%PY% -u tools\plot_e1.py --out results\20261029_e1c --workers 4 --noloop-long --iterations 20000
pause
