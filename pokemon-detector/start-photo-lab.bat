@echo off
setlocal
cd /d "%~dp0"
if not exist "private\evaluation-photos" mkdir "private\evaluation-photos"
echo.
echo ==================================================
echo BIGSTEN PHOTO GROUND TRUTH LAB - PRIVATE LOCAL ONLY
echo ==================================================
echo.
echo Place your authorized JPG / PNG / WebP images into:
echo   %cd%\private\evaluation-photos
echo.
echo Label review data will stay in:
echo   %cd%\private\reference-holdout.json
echo.
echo Open http://127.0.0.1:8766 in your browser after the server starts.
echo Do NOT expose this application to the internet.
echo.
py -3 photo_review_server.py --photos private\evaluation-photos --out private\reference-holdout.json --port 8766
if errorlevel 1 (
  echo.
  echo The lab did not start. Check that Python 3.12+ is installed
  echo and that the photo folder contains at least one valid image.
  echo See PHOTO_REVIEW_LAB.md for setup details.
  pause
)
