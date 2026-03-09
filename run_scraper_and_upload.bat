@echo off
setlocal EnableExtensions

REM Runs the PS5 scraper.
REM All R2 uploads (screenshots + JSON) are handled automatically by the scraper on exit.
REM Requires rclone installed and an r2ps5 remote configured.

set "BASE_DIR=C:\TEMP\testing\PS5"
set "SCRAPER=%BASE_DIR%\scraper_ps5.py"

cd /d "%BASE_DIR%" || exit /b 1

python "%SCRAPER%"

REM ── Optional completion sound ─────────────────────────────────────────────
powershell -NoProfile -Command ^
  "try { (New-Object Media.SoundPlayer 'C:\Windows\Media\Windows Notify System Generic.wav').PlaySync() } catch {}" ^
  >nul 2>&1

echo.
echo Done.
exit /b 0
