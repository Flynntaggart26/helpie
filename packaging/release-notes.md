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

- Fixed companion screen-frame metadata and expanded Turkish and English screen-question recognition. For a visible math question, compatible vision models can suggest underlines, equations and graphs on the companion overlay. Results depend on the selected model.
- Added an opt-in Groq multilingual speech mode for mixed Turkish and English. Choose it in Settings > Voice, provide a Groq speech key and enable its separate consent. Groq usage limits or charges may apply.
- Improved speech detection at the start of a phrase and kept the speaking heartbeat active when output audio levels are available. Thinking and speaking animations respect reduced-motion settings.
- Added separate removal controls for stored provider, Groq speech and wake-word keys. Removing a key from Helpie does not revoke it with its provider.
- Added confirmation for browser links and searches, bulk note and reminder deletion, memory deletion, routine deletion and computer power actions. File review now displays hidden direction controls in filenames.
- File organization is preview-only. File recycling, typing into other apps, multi-step chat plans and modifying plugin actions remain unavailable until safe review and execution are implemented. Some routines containing restricted actions will not run.

Existing installations keep their current recognition language and permissions. Multilingual speech is optional and sends recorded commands to Groq only after its separate permission is enabled. Actual recognition and screen-solution quality depend on the provider and model.
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
