# Helpie roadmap

This file tracks public status only. Detailed engineering decisions, threat
model and open product questions are maintained privately by the owner.

## Current release: v1.16.9

Helpie is a Windows desktop assistant: a small always-available window plus a
full chat/settings window, with a bundled Python backend and a Tauri/Rust shell.

v1.16.9 makes provider selection explicit and real: Settings -> AI Providers has
an "Active provider" page for Gemini, local Ollama, or a custom
OpenAI-compatible endpoint. Ollama runs locally without an API key, and if the
chosen provider is unreachable Helpie says so instead of falling back to
another one. This release also stops echoing the wake-word AccessKey to the
settings page and makes the Wake Word settings page reachable again.

v1.16.8 adds a visible cloud-voice indicator: while audio is sent to Google for
transcription, or text is sent to Edge for speech, the overlay shows a pulsing
"Cloud" badge. v1.16.7 restores the wake-word engine, off by default and gated
behind a user-supplied Picovoice AccessKey (built-in "jarvis"/"computer"
keywords; no custom "Hey Helpie" model is bundled). v1.16.6 enforces
screen-context consent at capture time: `capture_screen()` returns None unless
`screen_context_consent` is enabled in Settings -> Voice, so no plugin or
internal path can read the screen without consent. v1.16.5 shipped the consent
switch itself and completed Phase 1.

v1.16.4 is the v1.16.3 baseline plus a startup hotfix. v1.16.3 could not start:
the shell's own health probe was rejected by the Host validation added in the
same release, so the app always reported that the backend never answered. That
release is withdrawn; upgrades from it are manual because it cannot self-update.

v1.16.3 shipped the security baseline:

- authenticated local API (per-run token, loopback Host/Origin checks, body cap)
- tokenized shell control channel
- DPAPI-encrypted provider and plugin secrets, no secret echo to the UI
- explicit, off-by-default consent for cloud transcription and speech synthesis
- no screen capture in overlay mode; annotation-only and click-through
- plugins discoverable only from manifests, disabled by default, allowlisted,
  and documented as **not sandboxed**
- packaging guards that fail the build if per-user state appears in a package

## Phase 1 — complete (shipped in v1.16.5 / v1.16.6)

Goal: a Helpie presence that does not steal focus and can annotate the screen.

- tray icon and configurable global hotkey ✅
- transparent, always-on-top annotation window with a distinct Helpie cursor ✅
- clear states: idle, listening, thinking, speaking, drawing, paused, error ✅
- a single Stop that hides annotations and cancels the current task ✅
- multi-monitor placement and DPI handling ✅ (implemented; single-monitor tested)
- consent-based screen context: off by default, one-time grant in Settings ✅
  - consent enforced at the capture layer (`capture_screen()` returns None when off) ✅

## Next: Phase 2 candidates

- screen-context capture targets: monitor/window/region selection, a visible
  capture indicator, and screenshot timestamp/window metadata. The consent gate
  and capture-time enforcement are shipped; capture is still whole-desktop.
- visual answers (highlights, equations, graphs, geometry)
- policy-governed action broker
- tasks/plugins/chat consolidation
- interruptible speech and captions for voice replies
- signed beta (code-signing certificate required for SmartScreen)

Already shipped from this list: wake-word infrastructure (v1.16.7, off by
default, AccessKey-gated) and visible voice consent (v1.16.8).

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
