# Helpie roadmap

This file tracks public status only. Detailed engineering decisions, threat
model and open product questions are maintained privately by the owner.

## Current release: v1.16.3

Helpie is a Windows desktop assistant: a small always-available window plus a
full chat/settings window, with a bundled Python backend and a Tauri/Rust shell.
v1.16.3 shipped the security baseline:

- authenticated local API (per-run token, loopback Host/Origin checks, body cap)
- tokenized shell control channel
- DPAPI-encrypted provider and plugin secrets, no secret echo to the UI
- explicit, off-by-default consent for cloud transcription and speech synthesis
- no screen capture in overlay mode; annotation-only and click-through
- plugins discoverable only from manifests, disabled by default, allowlisted,
  and documented as **not sandboxed**
- packaging guards that fail the build if per-user state appears in a package

## Next: Phase 1, overlay shell and interaction model

Goal: a Helpie presence that does not steal focus and can annotate the screen.

- tray icon and configurable global hotkey
- transparent, always-on-top annotation window with a distinct Helpie cursor
- clear states: idle, listening, thinking, speaking, drawing, paused, error
- a single Stop that hides annotations and cancels the current task
- multi-monitor placement and DPI handling

Planned after that: consent-based screen context, voice in/out with visible
consent, visual answers (highlights, equations, graphs, geometry), a
policy-governed action broker, then tasks/plugins/chat consolidation and a
signed beta.

## Settled product scope

These are decisions, not open questions:

- **Windows 10 and 11, 64-bit.**
- **Screen context is off by default.** Enabling it is a one-time grant in
  Settings; nothing is captured until the user turns it on.
- **Both a cloud provider (Gemini) and local models (Ollama).** The user
  chooses. A local-only setup never sends data off the machine.
- **Helpie does not click or type for you.** It highlights and points; the
  overlay is click-through and never intercepts the pointer.
- **English UI; commands work in English and Turkish.**
- **Bundled, reviewed plugins only.** No third-party plugin distribution.

## Release rules

- Tag must equal `v` + `VERSION`; `Cargo.toml` and `tauri.conf.json` must match.
- Builds include only allowlisted plugin files and fail on known user state.
- No secrets, user data or build output in the repository or in release archives.
- Installers are currently unsigned, so SmartScreen shows "unknown publisher".

## Install

Download the latest installer or portable archive from
https://github.com/Flynntaggart26/helpie/releases, or build from source:

```powershell
python build_sidecar.py
npx --yes @tauri-apps/cli@2 build
```
