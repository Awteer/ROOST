@echo off
rem ============================================================
rem  44_plot_e1b.bat : draw E1b routes (phase 2 only, 2x2 maps per instance and seed)
rem  Output: results\20261029_e1b\png\
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
%PY% -u tools\plot_e1.py --out results\20261029_e1b --workers 4 --phase2-only --iterations 20000
pause
