@echo off
setlocal EnableExtensions

REM Runs the PS5 scraper then syncs outputs to R2 via rclone.
REM Requires rclone installed and an r2 remote configured (see README).

set "BASE_DIR=C:\TEMP\testing\PS5"
set "SCRAPER=%BASE_DIR%\scraper_ps5.py"

if not defined RCLONE_EXE set "RCLONE_EXE=rclone"
if not defined R2_REMOTE   set "R2_REMOTE=r2"

cd /d "%BASE_DIR%" || exit /b 1

REM ── Run the PS5 scraper ───────────────────────────────────────────────────
python "%SCRAPER%"
if errorlevel 1 (
  echo [ERROR] Scraper failed. Skipping upload.
  taskkill /F /IM chromedriver.exe /T >nul 2>&1
  exit /b 1
)

REM ── Upload JSON outputs ───────────────────────────────────────────────────
echo Uploading JSON outputs...
%RCLONE_EXE% copyto games_ps5.json       "%R2_REMOTE%:ps5/games_ps5.json"       --s3-no-check-bucket
%RCLONE_EXE% copyto games_ps5_cache.json "%R2_REMOTE%:ps5/games_ps5_cache.json" --s3-no-check-bucket
if errorlevel 1 echo [WARN] JSON upload reported an error.

REM ── Upload screenshots (new only, fast — no full bucket scan) ─────────────
echo Uploading screenshots (new only, fast — no full bucket scan)...
%RCLONE_EXE% copy screenshots_ps5 "%R2_REMOTE%:ps5" --no-traverse --s3-no-check-bucket
if errorlevel 1 echo [WARN] Screenshot upload reported an error.

REM ── Optional completion sound ─────────────────────────────────────────────
powershell -NoProfile -Command ^
  "try { (New-Object Media.SoundPlayer 'C:\Windows\Media\Windows Notify System Generic.wav').PlaySync() } catch {}" ^
  >nul 2>&1

echo.
echo Done.
exit /b 0
