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

- Visual annotations now use a versioned, bounded schema. Helpie clears them
  instead of rendering data from a schema version it does not support. You can
  ask it to add up to three numbered callouts along with pins, boxes and arrows.
- Helpie can place a plain-text or Unicode equation on the overlay and plot a
  bounded function graph. Graphs use a small arithmetic grammar and fixed SVG
  shapes; model text is never evaluated as code.
- When you explicitly ask the Ctrl+H companion to point something out, Helpie can
  show up to three temporary pins, numbered callouts, highlight boxes, or arrows.
  The coordinates are checked and rendered as fixed SVG shapes; they disappear
  after 12 seconds or when you say “clear highlights” / press Stop. The overlay
  stays click-through.
- The Notes page includes a local vector sketch pad. Drawings can be saved,
  reopened and edited; only the strokes are stored, and no screen image is saved.
- Ctrl+H now opens a compact desktop companion at the lower-right and hides the
  full chat window. A distinct Helpie pointer follows your cursor with a
  short smoothing transition; its current position is sampled locally and is not uploaded.
  The pointer now has a friendly face, and thinking uses three small dots beside a
  stationary “Thinking” label. Reduced-motion preferences disable the animations.
- Spoken assistant replies work without cloud speech permission through the
  installed Windows voice. Microsoft Edge neural speech remains optional; if it
  fails, Helpie falls back to the local Windows voice. Voice input consent is
  separate from voice output.
- When both screen-reading permissions are enabled, the Ctrl+H companion
  captures the primary display locally at up to one frame per second. It keeps
  only the newest reduced frame in memory for three seconds and captures a
  fresh one on demand if needed. No frame is sent to a model until you explicitly
  ask about the screen. A remote model receives only that requested frame; a
  local Ollama model keeps processing on this PC. Closing the companion or
  disabling either permission stops capture and clears the buffer.
- A visible overlay indicator labels local screen capture and shows when a
  single frame is being sent to a remote model. Full chat retains its separate
  explicit Windows picker for each screen question. Freehand drawing and saved
  notes directly over the live desktop, plus approved mouse/keyboard actions,
  remain future work. The Notes-page sketch pad is a separate local canvas.
- Screen questions now support image-capable OpenRouter and Groq models, as
  well as local Ollama vision models. No Gemini key is required when using
  those providers; cloud providers send the selected frame to their service.
- The Ollama settings explain that screen reading requires a vision model such
  as `gemma4`; its default text-only model cannot read images.
- The desktop updater now launches the downloaded installer through a robust
  handoff and explicit English/Turkish update requests route to Helpie's updater.
- Screen context uses the native Windows Graphics Capture picker for one-frame
  captures, with local region preview, capture status and target/time metadata.
- Screen capture remains off until the user enables it in Settings. Picker
  cancellation sends no frame.

The picker and live companion capture integrations compile in the locked
Windows release build. Interactive capture lifecycle and provider delivery
have not been runtime reviewed in this development environment.

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
