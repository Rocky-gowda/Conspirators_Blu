@echo off
REM Start Blu Visual Teacher fully offline. Double-click this file.
cd /d %~dp0
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set PY=python
where py >nul 2>nul && set PY=py -3.11
start "" http://127.0.0.1:8000
REM --host 0.0.0.0 lets a phone on the same hotspot open http://<laptop-ip>:8000
%PY% -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
pause
