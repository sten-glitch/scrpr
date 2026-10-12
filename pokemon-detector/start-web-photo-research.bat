@echo off
setlocal
cd /d "%~dp0"
echo =====================================================
echo BIGSTEN - PUBLIC PHOTO RESEARCH (PRIVATE LOCAL DATA)
echo =====================================================
echo.
echo Source: Wikimedia Commons / Pokemon Trading Card Game
echo Downloads only images with recognized per-file photo licenses.
echo Separate Pokemon artwork rights must be reviewed before commercial use.
echo This is NOT a verified Pokemon card identity dataset.
echo.
echo Photos stay in private\web-research\commons\, ignored by GitHub.
echo.
py -3 external_photo_sources.py commons --max-images 12
if errorlevel 1 (
  echo.
  echo Import did not finish. The site may be unavailable, rate-limited,
  echo or the destination already contains files. See WEB_IMAGE_DATASETS.md.
  pause
  exit /b 1
)
echo.
echo Open your PRIVATE local photo labeler at:
echo http://127.0.0.1:8766
echo.
py -3 photo_review_server.py --photos private\web-research\commons --out private\commons-photo-holdout.json --port 8766
if errorlevel 1 (
  echo Could not launch labeler. See PHOTO_REVIEW_LAB.md.
  pause
)
