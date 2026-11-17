# Helpie v__VERSION__

## Download

| File | Size | SHA-256 |
|---|---|---|
| `__SETUP_NAME__` | __SETUP_SIZE__ B | `__SETUP_SHA__` |
| `__PORTABLE_NAME__` | __PORTABLE_SIZE__ B | `__PORTABLE_SHA__` |
| `__SOURCE_NAME__` (source) | __SOURCE_SIZE__ B | `__SOURCE_SHA__` |

**Installer:** download `__SETUP_NAME__` and double-click it. No Python and no
administrator rights are needed.
**Portable:** download `__PORTABLE_NAME__`, extract anywhere, run `basla.bat`.

Verify a download with PowerShell:

```powershell
Get-FileHash .\__SETUP_NAME__ -Algorithm SHA256
```

## What changed

- The desktop updater now launches the downloaded installer through a robust
  handoff and explicit English/Turkish update requests route to Helpie's updater.
- Screen context uses the native Windows Graphics Capture picker for one-frame
  captures, with local region preview, capture status and target/time metadata.
- Screen capture remains off until the user enables it in Settings. Picker
  cancellation sends no frame.

The picker integration compiles in the locked Windows release build. Interactive
runtime review is still pending for picker selection, cancellation, capture
border behavior and one-frame provider delivery.

Commit history between the previous tag and `v__VERSION__`:

```powershell
git log --oneline v__VERSION__^..v__VERSION__
```

## Build provenance

These files were produced by the `Release` workflow from the `v__VERSION__`
tag. The workflow builds the Python sidecar with the packaging guards in
`build_sidecar.py` (allowlisted plugin files only, fail-closed on known
per-user state), then the Tauri installer. The portable archive contains the
same sidecar and shell binaries.

## Requirements

- Windows 10/11 (64-bit)
- Microsoft Edge WebView2 (the installer adds it automatically when missing)

The installer is not code-signed, so Windows SmartScreen shows "unknown
publisher". Click **More info -> Run anyway**; the source is in this
repository.

Existing installs update themselves from Settings, or automatically on startup
when a newer release exists.

Source: https://github.com/Flynntaggart26/helpie
