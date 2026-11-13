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
| Apps | Opens and closes Chrome, Spotify, Notepad, VS Code, Word, Explorer, Terminal… without stealing focus |
| Screen | Reads the current screen (including error messages) with the Gemini vision model |
| Documents | Summarises PDF, Word, PowerPoint and text files by name |
| Memory | Remembers lasting facts about you and uses them in conversation |
| Briefing | "Good morning" gives time, weather, battery, reminders and recent notes |
| Chains | Several commands in one sentence: "open Chrome and search for cats", "lock the screen, then take a screenshot" |
| Wake word | "Hey Helpie" / "Jarvis" starts listening hands-free (Porcupine, free tier) |
| Organize | Sort Desktop/Downloads/Documents by type or date, remove duplicates, clean empty folders |
| Plugins | Extensible system with example plugins: Clipboard History, System Monitor, Weather Extended |
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
- Python 3.10+ with `pyaudio`, `speechrecognition`, `edge-tts`, `pygame`, `requests`,
  `pillow` and `pypdf`
- Microsoft Edge (used as the app window) — preinstalled on Windows

Install the Python packages:

```powershell
## Design refresh (v1.4.0)

- New dark theme with deeper contrasts, refined accent blues and softer shadows
- Sidebar: wider (260px), cleaner logo, animated nav indicator, improved recent-chats list
- Messages: larger bubbles with asymmetric radii, subtle shadows, smoother enter animations
- Composer: larger hit areas, focus ring with accent glow, auto-resizing textarea
- Panels: consistent 16px radius, better typography hierarchy, hover lift on cards
- Micro-interactions: pulse glow on status dot, slide-down banners, staggered fades
- Accessibility: semantic roles, ARIA live regions, focus-visible outlines
- Scrollbars: thinner, themed, hidden track
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
- `What is on my screen` / `Ekranda ne var`, `Explain this error`
- `Summarize my thesis` / `Rapor dosyasını özetle`
- `Remember that I prefer short answers` / `Toplantı yarın, unutma`
- `What do you remember about me` / `Benim hakkımda ne hatırlıyorsun`
- `Forget everything` / `Hafızayı temizle`
- `Good morning` / `Günaydın` for a quick briefing
- `Open Chrome and search for cats` — chain commands with **and then**, **then**, **and**, **sonra** or **ve**
- `Sesi kıs ve parlaklığı azalt`, `Lock the screen, then take a screenshot`
- `Organize downloads by type` / `Organize desktop by date` — sort files into folders
- `Organize all preview` — dry-run across Desktop, Downloads, Documents
- `Remove duplicates in downloads` — delete duplicate files (keeps one copy)
- `Clean empty folders` — remove empty subfolders
- `Hey Helpie` / `Jarvis` — wake word to start listening hands-free (needs Porcupine AccessKey)

A longer list is in the **Commands** tab.

## Wake word (hands-free)

Say **“Hey Helpie”** or **“Jarvis”** and Helpie starts listening — no hotkey needed.

- Uses **Picovoice Porcupine** (runs locally, no cloud).
- Built-in keywords on free tier: **"Jarvis"**, **"Computer"**.
- Get a free AccessKey at <https://console.picovoice.ai/> and paste it in **Settings → Porcupine AccessKey**.
- Toggle with **Settings → Wake word: "Hey Helpie" / "Jarvis"**.
- Works alongside Ctrl+H; both trigger the same listening flow.
- Low CPU: runs in a background thread, only processes audio for keyword detection.

## File organizer

Organize folders by **type** (Images, Documents, Audio, Video, Archives, Code, etc.) or by **date** (YYYY-MM folders).

- `organize downloads by type` — moves files into category subfolders
- `organize desktop by date` — groups by modification month
- `organize all preview` — dry-run, shows what would move without doing it
- `remove duplicates in downloads` — finds identical files (by content hash), keeps one, deletes rest
- `clean empty folders` — recursively removes empty subdirectories

Add `preview` or `dry run` to any command to see what would happen without making changes.
Supports Turkish folder names: `masaüstü`, `indirilenler`, `belgeler`, `resimler`, `müzik`, `videolar`.

## Chained commands

One sentence can contain up to four actions:

- `open Chrome and search for cats`
- `open Notepad and take a screenshot`
- `sesi kıs ve parlaklığı azalt`
- `Chrome'u aç ve kedileri ara`
- `open chrome and spotify` — opens both apps in the background

Helpie splits the sentence only where both sides are real commands, so `take a note: milk and
eggs` or `search for rock and roll` stay a single action. When a free Gemini key is set, the
model can also emit a `plan` action with its own ordered steps.

Helpie splits the sentence only where both sides are real commands, so `take a note: milk and
eggs` or `search for rock and roll` stay a single action. When a free Gemini key is set, the
model can also emit a `plan` action with its own ordered steps.

## Plugin system

Helpie has a built-in plugin system that lets you extend its capabilities without modifying the core code.

### Included plugins

| Plugin | Description | Example commands |
|--------|-------------|------------------|
| **Clipboard History** | Persistent clipboard history with pin/recall | `clipboard history`, `pin clipboard`, `recall clipboard` |
| **System Monitor** | Real-time CPU, memory, disk, network, GPU stats | `system monitor`, `system stats`, `top processes`, `cpu usage`, `memory usage` |
| **Weather Extended** | 3-day forecasts and weather alerts (needs OpenWeatherMap API key) | `weather forecast`, `weather forecast`, `weather alerts` |

### Creating plugins

1. Create a folder under `plugins/` (e.g., `plugins/my_plugin/`)
2. Add `manifest.json` with name, version, entry point, permissions, and commands
3. Create `plugin.py` with a `Plugin` class that has `init(api)` and optional `shutdown()` methods
4. Restart Helpie — plugins are auto-discovered

### Plugin manifest example

```json
{
  "name": "my_plugin",
  "display_name": "My Plugin",
  "version": "1.0.0",
  "description": "Does cool things",
  "author": "Me",
  "entry": "plugin.py",
  "api_version": "1.0",
  "permissions": ["fs.read", "net.request", "voice.speak", "commands.register"],
  "commands": [
    {
      "name": "hello",
      "description": "Say hello",
      "handler": "say_hello",
      "patterns": ["hello plugin", "say hello"]
    }
  ]
}
```

### Plugin API

Plugins receive an `api` object in their `init(api)` method with these capabilities:

| Permission | Methods |
|------------|---------|
| `fs.read` / `fs.write` | `read_file(path)`, `write_file(path, content)` |
| `net.request` | `http_get(url, headers)`, `http_post(url, data, headers)` |
| `settings.read` / `settings.write` | `get_setting(key, default)`, `set_setting(key, value)` |
| `voice.speak` | `speak(text)` |
| `ui.render` | `show_toast(message)`, `add_sidebar_item(view_id, label, icon)` |
| `commands.register` | `register_command(name, handler, description, patterns)` |
| `system.exec` | `run_command(cmd_list)` |
| `screen.capture` | `capture_screen()` |
| `voice.speak` | `speak(text)` |

### Managing plugins

- **Settings → Plugins** tab (coming soon) — enable/disable/configure plugins
- CLI: `POST /api/plugins/load {"name": "plugin_name"}`, `POST /api/plugins/unload {"name": "..."}`
- Plugin settings: `POST /api/plugins/settings {"name": "...", "key": "...", "value": "..."}`

## Background apps

Opening something no longer pulls you away from what you are doing. Helpie starts apps and
links minimised (`SW_SHOWMINNOACTIVE`) and, if the app still grabs the foreground, a watcher
thread puts the previous window back in front. Turn it off with
**Settings → Open apps and links in the background**.

## Screen and documents

Screen reading and document summaries use Gemini vision, so they need a free API key.

- **Screen** — `What is on my screen`, `Explain this error`, `Ekranda ne var`. Helpie takes
  a downscaled screenshot, sends it to Gemini and answers out loud. DRM video players may
  appear black, and the window must not be minimised.
- **Documents** — `Summarize report`, `<name> dosyasını özetle`. Helpie finds the file on
  the Desktop, Documents or Downloads, extracts text from PDF/DOCX/PPTX/TXT and summarises
  it. Without an API key it falls back to a short extractive summary.

## Memory

Facts are stored in `data/memory.json` and appended to the model's system prompt, so Helpie
naturally remembers preferences across restarts. Manage them in **Notes → Memory**:
add a fact, forget one, or clear everything.

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
git tag v1.4.0
git push origin v1.4.0
```

## Project layout

```
helpie.py             launcher: server, browser window, global hotkey, --hidden mode
core/config.py        settings and paths, DPAPI-encrypted API key
core/voice.py         microphone capture (VAD + level + probe) and neural TTS
core/actions.py       Windows actions, clipboard, windows, quiet background launching
core/brain.py         intent rules + LLM handoff
core/llm.py           Gemini / OpenAI-compatible client, vision and summaries
core/documents.py     PDF/DOCX/PPTX/text extraction and summaries
core/memory.py        persistent facts (data/memory.json)
core/server.py        local HTTP server and JSON API
core/history.py       saved chats (data/history.json)
core/reminders.py     persistent scheduler (data/reminders.json)
core/notify.py        Windows notification balloons
core/secrets.py       DPAPI protect / unprotect
core/autostart.py     HKCU Run entry
core/updater.py       GitHub release updater
core/wintools.py      closes only Helpie's own browser window
core/plugins.py       plugin manager, loader, API
plugins/              plugin directory (example_weather, clipboard_history, system_monitor)
ui/                   chat + sidebar interface
```
