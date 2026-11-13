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
| Chat | Chat window with sidebar, saved history you can reopen and delete |
| Apps | Opens and closes Chrome, Spotify, Notepad, VS Code, Word, Explorer, Terminal… |
| Windows | Switches to a window by name, lists open windows, shows the desktop |
| Clipboard | Reads the clipboard out loud, copies text to it |
| System | Volume, brightness, media keys, screenshots, lock, shutdown, restart, sleep |
| Web | Google / YouTube search, direct site shortcuts |
| Notes | Saves notes to `data/notes.md`, list and clear from the UI |
| Reminders | One-off timers plus repeating reminders (daily / weekdays / weekly) that survive a restart and show a Windows notification |
| Math | "What is 15 percent of 240" |
| Chat | Free-form answers with a free Gemini API key |
| Privacy | The API key is encrypted with Windows DPAPI, never stored as plain text |
| Autostart | Optional silent start with Windows; Ctrl + H opens the window |
| Auto-update | Checks GitHub Releases, installs new versions in place |

The UI is a small chat window with a sidebar (Chat, Notes, Reminders, Commands, Settings),
so it behaves like a normal assistant app rather than a floating widget.

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
`basla.bat`. Starting it with `--hidden` keeps Helpie in the background: no window and no
greeting, Ctrl + H opens it when you need it. That is what the autostart option uses.

## Voice commands

Helpie answers in English but understands Turkish commands as well.

- `Open Chrome` / `Chrome'u aç`
- `Volume to 40` / `Sesi kıs`
- `Brightness 60` / `Parlaklığı azalt`
- `Take a note: buy milk`
- `Remind me in 10 minutes to stretch`
- `Remind me every day at 9 to drink water`
- `Show my reminders`
- `Read the clipboard` / `Panoyu oku`
- `Copy hello world to the clipboard`
- `Switch to Chrome` / `Chrome'a geç`
- `List my windows`, `Show the desktop`
- `Search the web for Mars rover` / `YouTube lo-fi beats`
- `Screenshot`, `Lock the screen`, `Battery status`
- `What time is it`, `What is 15 percent of 240`
- `Close Spotify`, `Open downloads`, `Type hello there`

A longer list is in the **Commands** tab.

## Reminders

Reminders are stored in `data/reminders.json`, so closing Helpie no longer cancels them.
When one is due, Helpie shows a Windows notification, says it out loud and posts it in the
chat. Repeating reminders move to their next occurrence automatically:

- `remind me in 20 minutes to stretch` — one-off
- `remind me every day at 9 to drink water` — daily
- `remind me every weekday at 8 to check email` — Monday to Friday
- `remind me every monday at 10 to plan the week` — weekly

They are listed in the **Reminders** tab, where you can delete them.

## AI brain (optional)

Built-in commands work offline-ish with no account. For real conversation, create a free
key at <https://aistudio.google.com/app/apikey> and paste it into **Settings → Gemini API key**.

The key is encrypted with Windows DPAPI (`api_key_enc` in `data/settings.json`); an old
plaintext key is migrated automatically on the next start. Without a key Helpie still
performs every command above; it just cannot answer open questions.

## Microphone troubleshooting

Settings → **Microphone test** records four seconds and shows a live level bar:

- **Good** — the microphone hears you.
- **Very quiet** — move closer or raise the input level.
- **No sound at all** — unmute the mic or pick another device.

If it stays silent:

1. Unmute the physical mic switch on your headset.
2. Windows → Settings → Privacy & security → Microphone → allow desktop apps.
3. Pick a different device in Helpie's settings.

The same hint appears in the chat when a voice command records silence.

## Autostart

**Settings → Start Helpie with Windows** writes a single value to
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`. It launches
`pythonw helpie.py --hidden`, so logging in does not pop a window; Ctrl + H opens it.

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
git tag v1.1.0
git push origin v1.1.0
```

## Project layout

```
helpie.py             launcher: server, browser window, global hotkey, --hidden mode
core/config.py        settings and paths, DPAPI-encrypted API key
core/voice.py         microphone capture (VAD + level + probe) and neural TTS
core/actions.py       Windows actions, clipboard and window helpers
core/brain.py         intent rules + LLM handoff
core/llm.py           Gemini / OpenAI-compatible client
core/server.py        local HTTP server and JSON API
core/history.py       saved chats (data/history.json)
core/reminders.py     persistent scheduler (data/reminders.json)
core/notify.py        Windows notification balloons
core/secrets.py       DPAPI protect / unprotect
core/autostart.py     HKCU Run entry
core/updater.py       GitHub release updater
core/wintools.py      closes only Helpie's own browser window
ui/                   chat + sidebar interface
```
