@echo off
REM Build the offline fallback lessons (run while run.bat is running).
cd /d %~dp0
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
set PY=python
where py >nul 2>nul && set PY=py -3.11
%PY% -m backend.prebake en hi mr --levels beginner intermediate --seconds 60
pause
