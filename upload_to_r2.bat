@echo off
setlocal EnableExtensions

REM Standalone upload script — run this after the scraper to sync outputs to R2.
REM Requires rclone installed and an r2ps5 remote configured (see README).

set "BASE_DIR=C:\TEMP\testing\PS5"

if not defined RCLONE_EXE set "RCLONE_EXE=rclone"
if not defined R2_REMOTE   set "R2_REMOTE=r2ps5"

cd /d "%BASE_DIR%" || exit /b 1

echo Uploading JSON outputs...
%RCLONE_EXE% copyto games_ps5.json       "%R2_REMOTE%:ps5/games_ps5.json"       --s3-no-check-bucket
%RCLONE_EXE% copyto games_ps5_cache.json "%R2_REMOTE%:ps5/games_ps5_cache.json" --s3-no-check-bucket
if errorlevel 1 echo [WARN] JSON upload reported an error.

echo Uploading screenshots (new only, fast — no full bucket scan)...
%RCLONE_EXE% copy screenshots_ps5 "%R2_REMOTE%:ps5" --no-traverse --s3-no-check-bucket
if errorlevel 1 echo [WARN] Screenshot upload reported an error.

echo.
echo Done.
