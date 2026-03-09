@echo off
setlocal EnableExtensions

REM Runs the PS5 scraper then syncs JSON outputs to R2 via rclone.
REM Screenshots are uploaded automatically by the scraper on exit.
REM Requires rclone installed and an r2ps5 remote configured (see README).

set "BASE_DIR=C:\TEMP\testing\PS5"
set "SCRAPER=%BASE_DIR%\scraper_ps5.py"

if not defined RCLONE_EXE set "RCLONE_EXE=rclone"
if not defined R2_REMOTE   set "R2_REMOTE=r2ps5"

cd /d "%BASE_DIR%" || exit /b 1

REM ── Run the PS5 scraper (also uploads screenshots to R2 on exit) ──────────
python "%SCRAPER%"

REM ── Upload JSON outputs ──────────────���────────────────────────────────────
echo Uploading JSON outputs...
%RCLONE_EXE% copyto games_ps5.json       "%R2_REMOTE%:ps5/games_ps5.json"       --s3-no-check-bucket
%RCLONE_EXE% copyto games_ps5_cache.json "%R2_REMOTE%:ps5/games_ps5_cache.json" --s3-no-check-bucket
if errorlevel 1 echo [WARN] JSON upload reported an error.

REM ── Optional completion sound ─────────────────────────────────────────────
powershell -NoProfile -Command ^
  "try { (New-Object Media.SoundPlayer 'C:\Windows\Media\Windows Notify System Generic.wav').PlaySync() } catch {}" ^
  >nul 2>&1

echo.
echo Done.
exit /b 0