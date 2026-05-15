// PS5 Game Browser — Tauri 2 backend (production)
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::process::Command;
use tauri::Manager;   // for app.get_webview_window() in single-instance callback

const GH_OWNER: &str = "NookieAI";
const GH_REPO:  &str = "PS5-Game-Scraper";

// ── GitHub API types ─────────────────────────────────────────────────────────
#[derive(Deserialize)]
struct GithubRelease {
    tag_name:    String,
    name:        Option<String>,
    body:        Option<String>,
    assets:      Vec<GithubAsset>,
    html_url:    String,
    prerelease:  bool,
}

#[derive(Deserialize)]
struct GithubAsset {
    name:                 String,
    browser_download_url: String,
    size:                 u64,
}

// ── Return type to the frontend ──────────────────────────────────────────────
#[derive(Serialize)]
struct UpdateInfo {
    available:    bool,
    current:      String,
    latest:       Option<String>,
    download_url: Option<String>,
    asset_name:   Option<String>,
    asset_size:   Option<u64>,
    release_url:  Option<String>,
    notes:        Option<String>,
    /// Filled when no compatible installer/exe found on the latest release,
    /// even though the version is newer. Frontend can show a link to the
    /// release page so user can install manually.
    error:        Option<String>,
}

// ── Public commands ──────────────────────────────────────────────────────────
#[tauri::command]
async fn check_for_updates() -> Result<UpdateInfo, String> {
    let current = env!("CARGO_PKG_VERSION").to_string();
    let release = fetch_latest_release().await
        .map_err(|e| format!("Update check failed: {e}"))?;

    let latest = release.tag_name.trim_start_matches('v').to_string();
    let release_url = Some(release.html_url.clone());
    let notes = release.body.clone();

    if !is_newer(&latest, &current) {
        return Ok(UpdateInfo {
            available: false, current, latest: Some(latest.clone()),
            download_url: None, asset_name: None, asset_size: None,
            release_url, notes, error: None,
        });
    }

    match find_asset_for_platform(&release.assets) {
        Some(asset) => Ok(UpdateInfo {
            available:    true,
            current,
            latest:       Some(latest.clone()),
            download_url: Some(asset.browser_download_url.clone()),
            asset_name:   Some(asset.name.clone()),
            asset_size:   Some(asset.size),
            release_url,
            notes,
            error:        None,
        }),
        None => Ok(UpdateInfo {
            available:    true,
            current,
            latest:       Some(latest.clone()),
            download_url: None,
            asset_name:   None,
            asset_size:   None,
            release_url,
            notes,
            error:        Some(format!(
                "v{latest} is available but no installer for this platform was found on the release."
            )),
        }),
    }
}

#[tauri::command]
async fn install_update(download_url: String,
                        asset_name:   Option<String>) -> Result<String, String> {
    // Download the installer to a temp file
    let client = reqwest::Client::builder()
        .user_agent("PS5GameBrowser-Updater/1.0")
        .build()
        .map_err(|e| format!("client init: {e}"))?;

    let bytes = client.get(&download_url)
        .send()
        .await
        .map_err(|e| format!("download request: {e}"))?
        .error_for_status()
        .map_err(|e| format!("download status: {e}"))?
        .bytes()
        .await
        .map_err(|e| format!("download body: {e}"))?;

    // Prefer the API-supplied filename (preserves spaces in "PS5 Game Browser.exe"
    // etc). Fall back to URL basename with %20 decoded if not provided.
    let safe_name = asset_name.unwrap_or_else(|| {
        download_url.rsplit('/')
            .next()
            .unwrap_or("ps5-game-browser-update.bin")
            .replace("%20", " ")
    });

    let temp_dir = std::env::temp_dir();
    let temp_file = temp_dir.join(&safe_name);
    std::fs::write(&temp_file, &bytes)
        .map_err(|e| format!("write temp: {e}"))?;

    let current_exe = std::env::current_exe()
        .map_err(|e| format!("current_exe: {e}"))?;
    let pid = std::process::id();

    spawn_updater(&temp_file, &current_exe, pid)
        .map_err(|e| format!("spawn updater: {e}"))?;

    Ok("Update downloaded — app will restart momentarily.".to_string())
}

// ── Internals ────────────────────────────────────────────────────────────────
async fn fetch_latest_release() -> Result<GithubRelease, String> {
    let url = format!(
        "https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/releases/latest"
    );
    let client = reqwest::Client::builder()
        .user_agent("PS5GameBrowser-Updater/1.0")
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client.get(&url).send().await.map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json::<GithubRelease>().await.map_err(|e| e.to_string())
}

/// Strict semver-ish comparison: split on '.' and compare numeric segments.
/// "1.2.3" > "1.2.0"  ;  "1.2.0" > "1.1.5" ;  "1.2" == "1.2.0".
/// Non-numeric junk in either side compares as 0 for that segment.
fn is_newer(latest: &str, current: &str) -> bool {
    fn parts(s: &str) -> Vec<u32> {
        s.split(|c: char| c == '.' || c == '-')
            .filter_map(|p| p.parse().ok())
            .collect()
    }
    let l = parts(latest);
    let c = parts(current);
    for i in 0..l.len().max(c.len()) {
        let lv = l.get(i).copied().unwrap_or(0);
        let cv = c.get(i).copied().unwrap_or(0);
        if lv > cv { return true; }
        if lv < cv { return false; }
    }
    false
}

/// Pick the right asset to download for the running platform.
fn find_asset_for_platform(assets: &[GithubAsset]) -> Option<&GithubAsset> {
    #[cfg(target_os = "windows")]
    {
        // Prefer the NSIS installer (x64-setup.exe) — handles file-replacement,
        // start-menu shortcut, uninstaller. Falls back to any .exe asset.
        if let Some(a) = assets.iter().find(|a|
            a.name.to_lowercase().ends_with("x64-setup.exe")
            || a.name.to_lowercase().contains("setup.exe")
        ) {
            return Some(a);
        }
        return assets.iter().find(|a| a.name.to_lowercase().ends_with(".exe"));
    }
    #[cfg(target_os = "macos")]
    {
        // .dmg for Intel/ARM. Architecture detection: at runtime
        // std::env::consts::ARCH is "aarch64" on M1, "x86_64" on Intel.
        let arch = std::env::consts::ARCH;
        if arch == "aarch64" {
            if let Some(a) = assets.iter().find(|a|
                a.name.to_lowercase().contains("aarch64")
                && a.name.to_lowercase().ends_with(".dmg")
            ) { return Some(a); }
        }
        return assets.iter().find(|a|
            a.name.to_lowercase().ends_with(".dmg")
            && !a.name.to_lowercase().contains("aarch64")
        );
    }
    #[cfg(target_os = "linux")]
    {
        // Prefer AppImage (self-contained, easy to swap). Fall back to .deb.
        if let Some(a) = assets.iter().find(|a|
            a.name.to_lowercase().ends_with(".appimage")
        ) { return Some(a); }
        return assets.iter().find(|a|
            a.name.to_lowercase().ends_with(".deb")
        );
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos", target_os = "linux")))]
    return None;
}

#[cfg(target_os = "windows")]
fn spawn_updater(downloaded: &PathBuf, current_exe: &PathBuf, pid: u32)
    -> Result<(), std::io::Error>
{
    use std::os::windows::process::CommandExt;
    const DETACHED_PROCESS:          u32 = 0x00000008;
    const CREATE_NEW_PROCESS_GROUP:  u32 = 0x00000200;
    const CREATE_NO_WINDOW:          u32 = 0x08000000;

    let script_path = std::env::temp_dir()
        .join("ps5-game-browser-update.bat");

    // NSIS silent install (/S). Installer overwrites current install location,
    // then we relaunch the newly-written exe.
    let script = format!(
        r#"@echo off
:waitloop
tasklist /FI "PID eq {pid}" 2>NUL | findstr /I /C:"{pid}" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto waitloop
)
timeout /t 1 /nobreak >nul
"{downloaded}" /S
timeout /t 3 /nobreak >nul
start "" "{current_exe}"
del "%~f0"
"#,
        pid          = pid,
        downloaded   = downloaded.display(),
        current_exe  = current_exe.display(),
    );
    std::fs::write(&script_path, script)?;

    Command::new("cmd")
        .args(&["/C", script_path.to_str().unwrap_or("")])
        .creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
        .spawn()?;
    Ok(())
}

#[cfg(target_os = "linux")]
fn spawn_updater(downloaded: &PathBuf, current_exe: &PathBuf, pid: u32)
    -> Result<(), std::io::Error>
{
    use std::os::unix::fs::PermissionsExt;
    let script_path = std::env::temp_dir().join("ps5-game-browser-update.sh");

    let is_deb = downloaded
        .extension()
        .map(|e| e == "deb")
        .unwrap_or(false);

    let script = if is_deb {
        // .deb extraction WITHOUT dpkg-deb. `ar` (binutils) is universally
        // available across distros — Fedora, Arch, openSUSE, Alpine, etc. all
        // ship binutils. We unpack debian's `ar` archive to a tempdir, then
        // expand data.tar.{gz,xz,zst} with progressive fallbacks.
        format!(
            r#"#!/bin/bash
set -e
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
sleep 1

EXTRACT_DIR="$(mktemp -d)"
cd "$EXTRACT_DIR"

# A .deb is an `ar` archive containing debian-binary, control.tar.*, data.tar.*.
ar x "{downloaded}"

# Locate the data tarball — compression varies between Tauri versions.
DATA_TAR="$(ls data.tar.* 2>/dev/null | head -1)"
if [ -z "$DATA_TAR" ]; then
    echo "Update failed: no data.tar.* in .deb"
    rm -rf "$EXTRACT_DIR" "{downloaded}"
    rm -f "$0"
    exit 1
fi

# Extract — tar auto-detects most compressions; zst needs explicit handling
# on older tar. Try modern tar first, fall back to unzstd if available.
case "$DATA_TAR" in
    *.zst)
        if tar --zstd -xf "$DATA_TAR" 2>/dev/null; then
            true
        elif command -v unzstd >/dev/null 2>&1; then
            unzstd -c "$DATA_TAR" | tar -xf -
        else
            echo "Update failed: tar lacks zstd support and unzstd not found"
            rm -rf "$EXTRACT_DIR" "{downloaded}"
            rm -f "$0"
            exit 1
        fi
        ;;
    *)
        # gz, xz, bz2, etc. — tar handles transparently with -xf
        tar -xf "$DATA_TAR"
        ;;
esac

# Locate the binary inside the extracted .deb tree. Three-tier strategy:
#   1. Tauri's standard install path (current): usr/bin/ps5-game-browser
#   2. Any ELF executable whose name contains ps5/game/browser fragments
#      (covers future Tauri layout changes like opt/PS5 Game Browser/)
#   3. Any ELF executable, last resort
NEW_BIN="$(find . -type f -name 'ps5-game-browser' | head -1)"

if [ -z "$NEW_BIN" ] && command -v file >/dev/null 2>&1; then
    while IFS= read -r candidate; do
        if file -b "$candidate" 2>/dev/null | grep -q 'ELF.*executable'; then
            case "$(basename "$candidate" | tr '[:upper:]' '[:lower:]')" in
                *ps5*|*browser*|*game*)
                    NEW_BIN="$candidate"
                    break
                    ;;
            esac
        fi
    done < <(find . -type f 2>/dev/null)
fi

if [ -z "$NEW_BIN" ] && command -v file >/dev/null 2>&1; then
    while IFS= read -r candidate; do
        if file -b "$candidate" 2>/dev/null | grep -q 'ELF.*executable'; then
            NEW_BIN="$candidate"
            break
        fi
    done < <(find . -type f 2>/dev/null)
fi

if [ -z "$NEW_BIN" ]; then
    echo "Update failed: no executable binary found in .deb"
    rm -rf "$EXTRACT_DIR" "{downloaded}"
    rm -f "$0"
    exit 1
fi

cp -f "$NEW_BIN" "{current_exe}"
chmod +x "{current_exe}"
rm -rf "$EXTRACT_DIR" "{downloaded}"
nohup "{current_exe}" >/dev/null 2>&1 &
rm -f "$0"
"#,
            pid = pid,
            downloaded = downloaded.display(),
            current_exe = current_exe.display(),
        )
    } else {
        // AppImage path — self-contained, just swap the file in place
        format!(
            r#"#!/bin/bash
set -e
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
sleep 1
chmod +x "{downloaded}"
mv -f "{downloaded}" "{current_exe}"
chmod +x "{current_exe}"
nohup "{current_exe}" >/dev/null 2>&1 &
rm -f "$0"
"#,
            pid = pid,
            downloaded = downloaded.display(),
            current_exe = current_exe.display(),
        )
    };
    std::fs::write(&script_path, script)?;
    std::fs::set_permissions(&script_path, std::fs::Permissions::from_mode(0o755))?;
    Command::new("bash").arg(&script_path).spawn()?;
    Ok(())
}

#[cfg(target_os = "macos")]
fn spawn_updater(downloaded: &PathBuf, current_exe: &PathBuf, pid: u32)
    -> Result<(), std::io::Error>
{
    use std::os::unix::fs::PermissionsExt;

    // current_exe points to .../MyApp.app/Contents/MacOS/binary — walk up
    // ancestors to find the .app bundle root we need to replace.
    let app_bundle = current_exe
        .ancestors()
        .find(|p| p.extension().map(|e| e == "app").unwrap_or(false))
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| {
            current_exe.parent()
                .and_then(|p| p.parent())
                .and_then(|p| p.parent())
                .map(|p| p.to_path_buf())
                .unwrap_or_else(|| current_exe.clone())
        });

    let script_path = std::env::temp_dir().join("ps5-game-browser-update.sh");
    let mount_point = std::env::temp_dir().join("ps5-browser-update-mount");

    // Flow:
    //   1. hdiutil attach the .dmg silently.
    //   2. Find the .app inside the mounted volume.
    //   3. Attempt `ditto` direct replace (no elevation).
    //   4. If ditto fails with permission errors (e.g. /Applications under
    //      parental controls, MDM-managed Mac, or a Gatekeeper-locked path),
    //      retry the replace via `osascript with administrator privileges`
    //      which surfaces a native Touch ID / password dialog with a custom
    //      prompt naming our app.
    //   5. Strip Gatekeeper quarantine xattr so first launch is silent.
    //   6. Detach, relaunch.
    let script = format!(
        r#"#!/bin/bash
set -e
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
sleep 1

mkdir -p "{mount}"
hdiutil attach "{downloaded}" -mountpoint "{mount}" -nobrowse -quiet

NEW_APP="$(find "{mount}" -maxdepth 2 -name '*.app' -type d | head -1)"
if [ -z "$NEW_APP" ]; then
    hdiutil detach "{mount}" -quiet || true
    rm -rf "{mount}" "{downloaded}"
    osascript -e 'display alert "Update failed: no .app found inside DMG."' >/dev/null 2>&1 || true
    rm -f "$0"
    exit 1
fi

# Try direct replace first (no password prompt). This works for the common
# case: app in ~/Applications, or /Applications when the user owns the dir.
DIRECT_OK=0
if rm -rf "{app_bundle}" 2>/dev/null && \
   ditto "$NEW_APP" "{app_bundle}" 2>/dev/null; then
    DIRECT_OK=1
fi

if [ "$DIRECT_OK" -eq 0 ]; then
    # Elevation path: ask the user for admin via a native Touch ID / password
    # dialog with a custom prompt that names the app. The shell command runs
    # as root inside osascript's privileged context, so /Applications writes
    # succeed even under MDM/parental restrictions.
    ELEVATED_SCRIPT="rm -rf '{app_bundle}' && ditto '$NEW_APP' '{app_bundle}' && xattr -dr com.apple.quarantine '{app_bundle}'"
    if ! osascript -e "do shell script \"$ELEVATED_SCRIPT\" with administrator privileges with prompt \"PS5 Game Browser needs permission to install the update.\"" >/dev/null 2>&1; then
        # User canceled the password dialog OR ditto failed even with root.
        hdiutil detach "{mount}" -quiet || true
        rm -rf "{mount}" "{downloaded}"
        osascript -e 'display alert "Update was cancelled or could not complete. The previous version is still installed."' >/dev/null 2>&1 || true
        rm -f "$0"
        exit 1
    fi
else
    # Direct path succeeded — strip quarantine ourselves so Gatekeeper doesn't
    # re-prompt the user on relaunch.
    xattr -dr com.apple.quarantine "{app_bundle}" 2>/dev/null || true
fi

hdiutil detach "{mount}" -quiet || true
rm -rf "{mount}" "{downloaded}"

open "{app_bundle}"
rm -f "$0"
"#,
        pid        = pid,
        downloaded = downloaded.display(),
        mount      = mount_point.display(),
        app_bundle = app_bundle.display(),
    );
    std::fs::write(&script_path, script)?;
    std::fs::set_permissions(&script_path, std::fs::Permissions::from_mode(0o755))?;
    Command::new("bash").arg(&script_path).spawn()?;
    Ok(())
}

// ── Tauri entrypoint ─────────────────────────────────────────────────────────
fn main() {
    tauri::Builder::default()
        // single-instance MUST be registered first. When a second copy of the
        // exe launches, this callback fires inside the FIRST instance with
        // the second one's argv + cwd, and the second process exits cleanly.
        // We use the AppHandle to find the main window, un-minimize it, and
        // bring it to the front so the user sees the existing app.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            check_for_updates,
            install_update,
        ])
        .run(tauri::generate_context!())
        .expect("error while running PS5 Game Browser");
}
