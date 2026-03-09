@echo off
setlocal EnableExtensions

set "BASE_DIR=C:\TEMP\testing\PS5"
set "SCRAPER=%BASE_DIR%\scraper_ps5.py"
set "UPLOADER=%BASE_DIR%\upload_to_r2.py"

REM ── R2 credentials ────────────────────────────────────────────────────────
REM Set these here OR pre-set them as Windows environment variables.
REM If already set in your system environment, these lines are skipped.
if not defined R2_ACCOUNT_ID        set "R2_ACCOUNT_ID=your-account-id-here"
if not defined R2_BUCKET            set "R2_BUCKET=ps5"
if not defined R2_ACCESS_KEY_ID     set "R2_ACCESS_KEY_ID=your-access-key-here"
if not defined R2_SECRET_ACCESS_KEY set "R2_SECRET_ACCESS_KEY=your-secret-key-here"

cd /d "%BASE_DIR%" || exit /b 1

REM ── Run the PS5 scraper ───────────────────────────────────────────────────
python "%SCRAPER%"
if errorlevel 1 (
  echo [ERROR] Scraper failed. Skipping upload.
  taskkill /F /IM chromedriver.exe /T >nul 2>&1
  exit /b 1
)

REM ── Upload to R2 bucket: ps5 ─────────────────────────────────────────────
REM upload_to_r2.py handles games.json, games_cache.json AND screenshots/
REM in a single fast pass — bulk key list, no per-file head_object calls.
python "%UPLOADER%"
if errorlevel 1 echo [WARN] Upload reported an error.

REM ── Optional completion sound ─────────────────────────────────────────────
powershell -NoProfile -Command ^
  "try { (New-Object Media.SoundPlayer 'C:\Windows\Media\Windows Notify System Generic.wav').PlaySync() } catch {}" ^
  >nul 2>&1

exit /b 0
