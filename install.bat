@echo off
REM One-time setup: installs the Python packages and the browser used for MP4 export.
cd /d %~dp0
set PY=python
where py >nul 2>nul && set PY=py -3.11
%PY% -m pip install -r requirements.txt
%PY% -m playwright install chromium
echo.
echo Setup finished. Now double-click run.bat (or type run.bat).
pause
