//! LEO PRODUCTS desktop shell.
//!
//! The window simply shows the LEO PRODUCTS web application (the URL is set in
//! tauri.conf.json -> app.windows[0].url). All data stays on the server: the desktop app
//! has no database and stores nothing except the browser session cookie, like a browser.
//! The remote site gets no access to Tauri/system APIs (no capabilities are granted to it).

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("error while running the LEO PRODUCTS desktop app");
}
