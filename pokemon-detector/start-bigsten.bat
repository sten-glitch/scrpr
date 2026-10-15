@echo off
setlocal
cd /d "%~dp0"
echo BIGSTEN Local Alpha - private localhost only
echo Open http://127.0.0.1:8765 in your browser.
py -3 local_app.py --port 8765
if errorlevel 1 (
  echo.
  echo Python 3 was not found or the local app failed to start.
  echo Install Python 3.12+ and see BIGSTEN_LOCAL_ALPHA.md.
  pause
)
