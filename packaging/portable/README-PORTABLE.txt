Helpie Portable - v__VERSION__
=========================

No installer. Extract this folder anywhere and run `basla.bat` (or
double-click `helpie.exe`).

Requirements:
- Windows 10/11 64-bit
- Microsoft Edge WebView2 (the portable zip does NOT install it - if a
  window fails to open, install WebView2 from
  https://go.microsoft.com/fwlink/p/?LinkId=2124703)

What's inside:
- helpie.exe        - the Helpie shell (Tauri window)
- helpie-core/      - the bundled Python assistant engine (runs beside the exe)
- basla.bat         - one-click launcher

Settings, chat history and your encrypted API key are stored in
%APPDATA%\Helpie, so they follow your Windows account no matter where you
extract this folder.

"Windows protected your PC" (unknown publisher): Helpie is not code-signed,
so SmartScreen shows a warning. Click More info -> Run anyway.

Source: https://github.com/Flynntaggart26/helpie
