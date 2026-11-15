# Helpie — instructions for every agent

## Hard rule: no voice during development

**Never activate the microphone or the voice-chat flow while building, debugging,
or testing Helpie. Use text only.**

That means:

- Do not press the hotkey, say the wake word, or call `/api/listen`, `/api/ask`
  with a voice turn, or `app.listen_async(...)`.
- Do not run `helpie.py` in its default mode "to see if it works" — it greets out
  loud and starts listening.
- When you must start the app for a smoke test, set `HELPIE_NO_VOICE=1` (disables
  wake word, auto-listen and continuous mode) and run it with `--hidden`.
- Voice is used only when the user explicitly asks for a voice/audio test.

Speech output (TTS) is also skipped in `--hidden` mode, so hidden smoke tests are
fully silent.

## What Helpie is

A Windows voice assistant. `Ctrl+H` (or a wake word) opens the tiny window, the
user asks something, Helpie answers and optionally performs an action.

- UI copy and assistant replies are English; the user speaks Turkish. Turkish
  commands must keep working.
- Windows the app opens must never steal focus / pop in front of the user's work.
  The wake word opens the **tiny** window only, never the full app.

## Layout

```
helpie.py            entry point (dev + sidecar)
core/                config, server, actions, brain, voice, updater, shell bridge
plugins/             drop-in feature plugins
ui/                  the entire frontend (index.html, app.js, style.css)
web/                 splash page shown by the Tauri shell while the backend boots
src-tauri/           Tauri v2 desktop shell (Rust) + installer config
build_sidecar.py     PyInstaller -> src-tauri/binaries/helpie-core-<triple>.exe
```

## Architecture

- The **Tauri shell** owns every window. It picks a port, spawns the Python
  backend as a sidecar (`helpie-core.exe`), waits for `/api/health`, then loads
  `http://127.0.0.1:<port>/`.
- The backend talks to the shell over a localhost control endpoint
  (`core/shell.py` → `full`, `tiny`, `hide-tiny`, `quit`). It receives the port
  through `HELPIE_CONTROL_PORT`.
- Without a shell (`python helpie.py`), `core/shell.py` is a no-op and the old
  Edge/Chrome `--app` window is used instead. Both modes must keep working.

## Environment variables

| Variable | Meaning |
|---|---|
| `HELPIE_PORT` | Port the backend must listen on (set by the shell) |
| `HELPIE_CONTROL_PORT` | Shell control endpoint port |
| `HELPIE_NO_BROWSER` | Never open an Edge/Chrome window |
| `HELPIE_NO_VOICE` | Disable wake word / auto-listen (development) |
| `HELPIE_DATA_DIR` | Override the writable data directory |
| `HELPIE_REPO` | GitHub repo used by the updater (forks) |
| `GEMINI_API_KEY` / `OPENAI_KEY` | Provider keys (optional) |

## Data location

- Development: `data/` in the project (gitignored).
- Installed build: `%APPDATA%\Helpie` (Program Files is read-only).
- `settings.json` holds the DPAPI-encrypted key. `data/` must **never** be added
  to a PyInstaller `--add-data` list or to a release asset.

## Build and release

```powershell
python make_icons.py          # once, or when the logo changes
python build_sidecar.py       # Python backend -> src-tauri/binaries/
npx @tauri-apps/cli@2 build   # -> src-tauri/target/release/bundle/nsis/*.exe
```

- `VERSION`, `src-tauri/tauri.conf.json` and `src-tauri/Cargo.toml` must agree.
- Tag = `v` + trimmed `VERSION`. The release workflow builds the installer and
  the source zip.
- `dist/`, `build/`, `target/`, `binaries/` and `*.spec` stay out of git.

## Conventions

- Python: 4 spaces, `from __future__ import annotations`, no `print` noise in
  the request path, never raise out of the audit log.
- Frontend: plain ES modules in `ui/app.js`, no build step, no new dependencies.
- Every user-facing action goes through `core/audit.py`.
- Keep the exe portability promise: no absolute paths, no secrets, works on a
  fresh Windows 11 machine with WebView2.
