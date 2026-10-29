@echo off
rem Pick the Python command: "py -3" (Python launcher) if present, else "python".
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
