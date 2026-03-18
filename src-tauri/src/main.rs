// PS5 Game Browser — Tauri backend
// All data fetching happens in the frontend via fetch() to the public CDN.
// The only Rust-side concern is opening external URLs in the system browser.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running PS5 Game Browser");
}
