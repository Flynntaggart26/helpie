# Helpie

A small voice assistant that lives on your Windows desktop. Press **Ctrl + H**, speak, and
Helpie listens, understands and answers out loud — while also controlling the machine for you.

```
Ctrl + H  →  microphone opens  →  you speak  →  Helpie answers and acts
```

## Features

| Area | What it does |
| --- | --- |
| Voice | Global hotkey, speech recognition, natural neural voice replies |
| Apps | Opens and closes Chrome, Spotify, Notepad, VS Code, Word, Explorer, Terminal… |
| System | Volume, brightness, media keys, screenshots, lock, shutdown, restart, sleep |
| Web | Google / YouTube search, direct site shortcuts |
| Notes | Saves notes to `data/notes.md`, list and clear from the UI |
| Timers | "Remind me in 10 minutes to stretch" |
| Math | "What is 15 percent of 240" |
| Chat | Free-form answers with a free Gemini API key |
| Auto-update | Checks GitHub Releases, installs new versions in place |

The UI is a small chat window with a sidebar (Chat, Notes, Commands, Settings), so it
behaves like a normal assistant app rather than a floating widget.

## Requirements

- Windows 10/11
- Python 3.10+ with `pyaudio`, `speechrecognition`, `edge-tts`, `pygame`, `requests`
- Microsoft Edge (used as the app window) — preinstalled on Windows

Install the Python packages:

```powershell
python -m pip install pyaudio speechrecognition edge-tts pygame requests
```

## Run

```powershell
python helpie.py
```

or double-click **`basla.bat`** (runs without a console window).

The first launch creates `data/settings.json`. A shortcut on the desktop can point at
`basla.bat`.

## Voice commands

Helpie answers in English but understands Turkish commands as well.

- `Open Chrome` / `Chrome'u aç`
- `Volume to 40` / `Sesi kıs`
- `Brightness 60` / `Parlaklığı azalt`
- `Take a note: buy milk`
- `Remind me in 10 minutes to stretch`
- `Search the web for Mars rover` / `YouTube lo-fi beats`
- `Screenshot`, `Lock the screen`, `Battery status`
- `What time is it`, `What is 15 percent of 240`
- `Close Spotify`, `Open downloads`, `Type hello there`

A longer list is in the **Commands** tab.

## AI brain (optional)

Built-in commands work offline-ish with no account. For real conversation, create a free
key at <https://aistudio.google.com/app/apikey> and paste it into **Settings → Gemini API key**.

Without a key Helpie still performs every command above; it just cannot answer open questions.

## Microphone troubleshooting

Settings → **Microphone** lets you pick the input device. If the level meter stays at zero:

1. Unmute the physical mic switch on your headset.
2. Windows → Settings → Privacy & security → Microphone → allow desktop apps.
3. Pick a different device in Helpie's settings.

## Auto-update

`VERSION` holds the current version. A GitHub Actions workflow (`.github/workflows/release.yml`)
runs on every `v*` tag, zips the repository and publishes it as a GitHub Release.

At startup Helpie asks GitHub for the latest release:

- newer tag → the sidebar shows “Helpie x.y.z is available”, with an **Install** button
- **Install** downloads the zip, copies the files over the app folder (keeping `data/`) and restarts

Manual check: **Check for updates** in the sidebar.

Releasing a new version:

```powershell
# bump VERSION first, then
git tag v1.0.1
git push origin v1.0.1
```

## Project layout

```
helpie.py            launcher: server, browser window, global hotkey
core/config.py       settings + paths
core/voice.py        microphone capture (VAD + level) and neural TTS
core/actions.py      Windows actions
core/brain.py        intent rules + LLM handoff
core/llm.py          Gemini / OpenAI-compatible client
core/server.py       local HTTP server and JSON API
core/updater.py      GitHub release updater
ui/                  chat + sidebar interface
```
