@echo off
rem ============================================================
rem  10_test.bat : run the ROOST tests (about a few seconds)
rem  XIAO is read from ..\XIAO (C:\Research\code\XIAO) unless XIAO_PATH is set.
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0.."
call "%~dp0_python.bat"
%PY% -m pytest -q tests
pause
