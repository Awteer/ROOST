@echo off
rem ============================================================
rem  30_run_alns.bat : solve one Xiao-type instance with ROOST's ALNS
rem  Edit the settings below.
rem    INSTANCE : "n.d.m.h" (e.g. 20.20.1.a).  One truck: total demand must be <= 300 kg.
rem    MODES    : 1 truck only, 2 no NCR no loop, 3 no NCR loop, 4 NCR no loop, 5 NCR loop
rem    GRID     : NCR candidates on a GRID x GRID lattice (depot point excluded)
rem  Output: results\YYYYMMDD_<NAME>\ (README.md, meta.json, config.yaml, raw\)
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
set INSTANCE=20.20.1.a
set MODES=2 3 4 5
set GRID=7
set ITER=5000
set SEEDS=1 2 3
set NAME=n20-grid7
%PY% -u tools\run_alns.py --instance %INSTANCE% --modes %MODES% --ncr-grid %GRID% --iterations %ITER% --seeds %SEEDS% --name %NAME%
pause
