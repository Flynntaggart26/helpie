# Helpie v2.0+ Feature Roadmap

## Shipped in v1.16.0 — the Tauri desktop app
- [x] Windows installer (`Helpie_1.16.0_x64-setup.exe`, Tauri v2 + NSIS), no Python required
- [x] Python backend bundled as a sidecar (`helpie-core.exe`)
- [x] Tiny wake-word window as a real popup (time, weather, next reminder)
- [x] Silent autostart; Ctrl+H brings the window up
- [x] Installer-aware self-update
- [x] User data in `%APPDATA%\Helpie`
- [ ] Tray icon with quick actions
- [ ] Single-instance enforcement (currently a second launch reuses the backend)
- [ ] Code signing certificate (removes the SmartScreen "unknown publisher" warning)
- [ ] Signed auto-updater (`tauri-plugin-updater`) instead of downloading the setup.exe

## Phase 1: Core Integrations (Week 1-2) - HIGH IMPACT, LOW EFFORT
- [ ] Spotify plugin (play/pause/next/prev/search/playlists)
- [ ] Notion plugin (create pages, search, append to daily notes)
- [ ] Home Assistant plugin (lights, climate, sensors)
- [ ] GitHub plugin (issues, PRs, search)
- [ ] Calendar plugin (CalDAV/Google - full CRUD)

## Phase 2: AI & Offline Capabilities (Week 2-3)
- [ ] Ollama integration (local LLM via HTTP API)
- [ ] Function calling with local LLM (structured output)
- [ ] RAG over local files (embeddings + vector search)
- [ ] Voice cloning (XTTS/Coqui TTS)
- [ ] Custom wake word training (Picovoice)

## Phase 3: UI/UX Polish (Week 3)
- [ ] Plugin marketplace UI (browse/install from GitHub)
- [x] Routine builder (visual editor — list, create, run, delete, templates)
- [x] Dashboard widgets on tiny window (time, weather, next reminder)
- [x] Command palette (Ctrl+Space fuzzy search)
- [x] Themes (dark, light, high-contrast)

## Phase 4: Advanced AI (Week 4)
- [ ] RAG over local files (embeddings + vector search)
- [ ] Multi-turn conversation context
- [ ] Proactive suggestions ("You usually open Chrome at 9 AM")
- [ ] Intent confidence scoring in UI

## Phase 5: Privacy & Security (Week 5)
- [ ] Encrypted data at rest (DPAPI/user passphrase)
- [x] Audit log (all actions timestamped)
- [ ] Permission prompts on first plugin use
- [ ] Sandboxed plugins (WASM/subprocess isolation)

## Phase 6: Advanced Integrations (Week 6+)
- [ ] Spotify plugin (playlists, search, playback control)
- [ ] Discord/Teams/Slack plugins
- [ ] Notion/Obsidian plugins
- [ ] Jira/Linear/GitHub plugins
- [ ] Home Assistant (lights, climate, sensors)
- [ ] Calendar (CalDAV/Google - full CRUD)

---

## Implementation Order (by ROI)

1. **Spotify + Notion + Home Assistant plugins** → Immediate daily utility
2. **Ollama integration** → Offline/private chat, fallback when no API key
3. **Routine marketplace** → Share/import via GitHub Gists
4. **Command palette** → Ctrl+Space fuzzy search
5. **Plugin marketplace UI** → Browse/install from GitHub
6. **Routine builder UI** → Visual drag-drop editor
5. **Ollama + function calling** → Offline function calling
6. **RAG over local files** → "Summarize my project docs"
6. **Voice cloning** → Your own voice
7. **Custom wake word** → "Hey Helpie"
7. **Plugin marketplace UI** → Browse/install from GitHub
7. **Routine builder UI** → Visual drag-drop editor
7. **Dashboard widgets** → CPU, weather, calendar on tiny window
7. **Command palette** → Ctrl+Space fuzzy search
7. **Themes** → Light, high-contrast, custom CSS
7. **Encrypted data at rest** → DPAPI/user passphrase
7. **Audit log** → All actions timestamped
7. **Permission prompts** → "Allow Helpie to access email?"
7. **Sandboxed plugins** → WASM/subprocess isolation

---

## Technical Architecture

### Plugin System Extensions
```
plugins/
  spotify/
    manifest.json
    plugin.py
  notion/
    manifest.json
    plugin.py
  home_assistant/
    manifest.json
    plugin.py
  ollama/
    manifest.json
    plugin.py
```

### Routine Marketplace
```
routines/
  marketplace/
    index.json          # Index of shared routines
    morning_gist.json   # GitHub Gist ID
  user/
    morning.json        # Local routines
```

### Ollama Integration
```python
# core/ollama.py
class OllamaClient:
    def __init__(self, base_url="http://localhost:11434"):
        self.base_url = base_url
    
    def chat(self, messages, model="llama3.2", tools=None):
        # Function calling support
        pass
    
    def embed(self, texts, model="nomic-embed-text"):
        # Embeddings for RAG
        pass
```

### RAG System
```
data/
  embeddings/
    index.faiss         # Vector index
    metadata.json       # Chunk metadata
  documents/            # Source files for RAG
```

---

## Quick Wins (Do First)

1. **Spotify plugin** - 2 hours, high daily use
2. **Notion plugin** - 3 hours, knowledge workers love it
3. **Home Assistant** - 3 hours, smart home control
4. **Ollama client** - 4 hours, enables offline mode
5. **Command palette** - 3 hours, power user feature