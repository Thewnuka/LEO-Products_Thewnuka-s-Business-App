# LEO PRODUCTS — Windows desktop app (Tauri)

A small Windows program that opens the LEO PRODUCTS web application in its own window
(no browser tabs or address bar), with the LEO PRODUCTS icon in the Start menu and taskbar.

* It uses the **same server and database** as the website. The desktop app has no database
  of its own and keeps no business data; it is a window onto the server.
* The server must be running and reachable. For a hosted server this needs **internet access**.

> **Status:** this folder contains the complete project, but the installer has **not been built
> yet**: the computer used for development had no Rust toolchain. Follow the steps below on a
> Windows PC to build and test it.

## 1. Choose the server address

Edit `src-tauri/tauri.conf.json` → `app.windows[0].url`:

| Situation | URL |
|---|---|
| Server runs on the same shop PC (Waitress, see DEVELOPMENT_GUIDE) | `http://127.0.0.1:8000/staff/login/` (default) |
| Hosted server | `https://YOUR-DOMAIN/staff/login/` (use HTTPS) |

The address is fixed when the installer is built; rebuild after changing it.

## 2. Install the build tools (one time)

1. **Microsoft C++ Build Tools**: install "Desktop development with C++" from
   <https://visualstudio.microsoft.com/visual-cpp-build-tools/>.
2. **Rust**: install from <https://rustup.rs/> (default options), then open a new PowerShell window.
3. **Node.js 18 or newer** (only needed to run the Tauri build tool).
4. **WebView2** is included in Windows 10 (recent updates) and Windows 11. The installer downloads it if missing.

Check:

```powershell
rustc --version
cargo --version
node --version
```

## 3. Build the installer

```powershell
cd desktop
npm install
npm run build
```

The installers are created in:

* `src-tauri\target\release\bundle\nsis\LEO PRODUCTS_1.0.0_x64-setup.exe` (recommended)
* `src-tauri\target\release\bundle\msi\LEO PRODUCTS_1.0.0_x64_en-US.msi`

`npm run dev` opens the window without building an installer (for a quick test).

## 4. Test before handing it out

1. Start the server and open the configured URL in a browser to be sure it works.
2. Install the `.exe`, open **LEO PRODUCTS** from the Start menu.
3. Sign in, open the till, print a receipt (the Windows print dialog should appear), sign out.
4. Stop the server and reopen the app: you should see the "server can't be reached" page, not an error.

## Notes

* Code signing: Windows SmartScreen may warn about an unsigned installer. Signing needs a code-signing
  certificate (not included); see the Tauri documentation on Windows code signing.
* Security: the LEO PRODUCTS website is loaded as a remote page and is given **no** access to Tauri or
  system features. Sign-in, permissions and all data stay on the server exactly as in a browser.
* Icons in `src-tauri/icons` were generated from the official logo (`static/images/leo-logo.png`).
