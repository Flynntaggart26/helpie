# Helpie roadmap

This file tracks public status only. Detailed engineering decisions, threat
model and open product questions are maintained privately by the owner.

## Current release: v1.16.15

Installer and portable downloads are available on the [GitHub release page](https://github.com/Flynntaggart26/helpie/releases/tag/v1.16.15).

v1.16.15 adds temporary, model-proposed screen pins/highlights/arrows for direct
requests, a friendlier companion cursor with a three-dot thinking state, and a
local sketch pad in the Notes page. Visual notes store bounded vector strokes
and, in the unreleased v1.16.16 candidate, validated vector answers; no screen
images are stored.

## Work in progress: v1.16.16 candidate (not released)

Visual annotation proposals now use schema version 1. The backend rejects
missing or unsupported schema versions, and the desktop overlay clears rather
than rendering annotation data from an unknown version. Numbered callouts are
also available alongside pins, rectangles and arrows.
Visual answers can also render plain-text/Unicode equations and plot bounded
functions with a fixed SVG renderer; the backend parses a small arithmetic
grammar and samples a fixed domain without evaluating code.
Basic point, segment, circle and polygon diagrams support plain-text labels and
visual relation marks for horizontal, vertical, equal, perpendicular and
parallel segments; these marks do not solve or alter geometry.
The Notes editor can import the latest vector answer while it remains in memory,
save and reopen it with sketch strokes, undo edits, and export a local JSON file.

Helpie is a Windows desktop assistant: a small always-available window plus a
full chat/settings window, with a bundled Python backend and a Tauri/Rust shell.

v1.16.13 extends the companion with opt-in local live screen context. When both
screen-reading permissions are enabled, the primary display is captured locally
at up to one frame per second while Ctrl+H is open. Only the newest reduced
frame is held in memory for three seconds; a fresh frame is captured if needed
when the user explicitly asks about the screen. Only that requested frame is
sent to the selected model. Closing the companion stops capture and clears the
buffer. The overlay visibly labels local capture and remote versus local model
processing. Full chat retains its separate one-frame Windows picker flow.
Drawing, highlights, notes on the overlay, and approved desktop actions are
still future work.

v1.16.14 removes the two-second pointer lag; Helpie's distinct marker follows
the current cursor with a short smoothing transition. Replies now use an
installed Windows voice locally when cloud neural speech is not enabled, and
fall back to local speech if the online synthesizer or audio playback fails.

v1.16.12 introduced Ctrl+H companion placement, a distinct local pointer echo,
and tray/full-window lifecycle behavior.

v1.16.11 adds image-capable vision requests for OpenRouter, Groq and local
Ollama models. Cloud vision sends the selected frame to the selected provider;
Ollama keeps it on this PC. Gemini remains available. Use a vision-capable model
such as `gemma4` for Ollama; its default text model cannot read images.

v1.16.10 repairs desktop self-updates by routing explicit English and Turkish
update commands through the trusted updater and launching the downloaded setup
through a quoted handoff script. The installed app keeps settings and user data
in `%APPDATA%\Helpie`. It also ships the consent-based Windows Graphics Capture
picker, one-frame capture, local region preview, capture status and target/time
metadata. The native picker builds successfully; interactive runtime validation
remains open, so this release is not the completion of Phase 2 capture review.

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

- screen-context capture targets: Windows Graphics Capture picker, one-frame
  capture, visible capture indicator and timestamp/target metadata are included
  in v1.16.10; interactive runtime review is still open.
- vision adapters for Gemini, OpenRouter, Groq and local Ollama are included in
  v1.16.11; cloud providers require their own key and an image-capable model.
- visual answers (highlights, equations, graphs, geometry)
- policy-governed action broker
- tasks/plugins/chat consolidation
- interruptible speech and captions for voice replies
- signed beta (code-signing certificate required for SmartScreen)

Already shipped from this list: wake-word infrastructure (v1.16.7, off by
default, AccessKey-gated) and visible voice consent (v1.16.8).

### Phase 2 capture integration in v1.16.10 (runtime review open)

- The desktop shell uses Windows Graphics Capture and opens the system picker
  for each user-requested screen question. The selected window or display yields
  one in-memory PNG frame; cancel or capture failure returns no image. The frame
  is transferred over the authenticated shell control channel and is not saved.
- The optional region preview also uses the system picker and stays local to the
  desktop UI. A saved normalized crop is applied to the next selected frame.
- The app shows a capture state and includes a timestamp plus the picker target
  name when Windows provides one.

The native integration compiles in a locked Windows release build. Runtime
review is still needed for picker selection, cancellation, the Windows capture
border, and the one-frame provider flow before calling this Phase 2 slice
complete. The browser development mode retains the Pillow fallback.

### Image-capable AI providers in v1.16.11

- OpenAI-compatible vision requests send the selected frame as a data URL to
  the configured endpoint. OpenRouter and Groq use the existing encrypted key
  setting; choose an image-capable model from the provider.
- Ollama vision requests keep the frame on the local machine. Configure a
  vision-capable model such as `gemma4`; the default `llama3.2` is text-only.
- Gemini remains supported. Helpie does not switch providers automatically.

## Settled product scope

These are decisions, not open questions:

- **Windows 10 and 11, 64-bit.**
- **Screen context is off by default.** Enabling it is a one-time grant in
  Settings; nothing is captured until the user turns it on.
- **Cloud or local models.** Gemini, OpenRouter, and Groq are supported as
  cloud providers; Ollama can run locally. The user chooses, and a local-only
  setup never sends data off the machine.
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
