const $ = (id) => document.getElementById(id);

const state = {
  settings: {},
  mics: [],
  voices: [],
  languages: [],
  lastEvent: 0,
  busy: false,
  update: null,
  view: "chat",
  chats: [],
  currentChat: null,
  reminders: [],
  routines: [],
  memory: [],
  micTesting: false,
  settingsPage: "general",
  theme: "dark",
  pluginFilter: "all",
  auditSource: "",
  scope: "all",
};

const SETTINGS_PAGES = {
  general: ["General"],
  voice: ["Voice"],
  wakeword: ["Wake Word"],
  "provider-gemini": ["AI Providers", "Gemini"],
  "provider-ollama": ["AI Providers", "Ollama"],
  "provider-custom": ["AI Providers", "Custom OpenAI"],
  plugins: ["Plugins"],
  activity: ["Activity"],
  shortcuts: ["Shortcuts"],
  about: ["About"],
};

const SCOPE_PAGES = {
  all: null,
  ai: ["provider-gemini", "provider-ollama", "provider-custom"],
  plugins: ["plugins"],
};

const STATUS = {
  idle: "ready",
  listening: "listening",
  hearing: "hearing you",
  thinking: "thinking",
  speaking: "speaking",
};

const COMMANDS = [
  ["Open apps", '"Open Chrome", "Launch Spotify", "Close Notepad"'],
  ["Volume", '"Volume to 40", "Mute", "Turn the volume up"'],
  ["Brightness", '"Brightness 60", "Dim the screen"'],
  ["Search", '"Search the web for Mars", "YouTube lo-fi beats"'],
  ["Screen", '"What is on my screen", "Explain this error", "Ekranda ne var"'],
  ["Documents", '"Summarize my thesis", "Report dosyasını özetle"'],
  ["Memory", '"Remember that I prefer short answers", "What do you remember about me"'],
  ["Briefing", '"Good morning", "Give me a briefing"'],
  ["Chain commands", '"Open Chrome and search for cats", "Sesi kıs ve parlaklığı azalt", "Lock the screen, then take a screenshot"'],
  ["Organize files", '"Organize downloads by type", "Organize desktop by date", "Organize all preview", "Remove duplicates in downloads", "Clean empty folders"'],
  ["Wake word", '"Hey Helpie" / "Jarvis" — starts listening without Ctrl+H (needs Porcupine AccessKey)'],
  ["Routines", '"Run start_work routine", "Save routine my_morning", "Run routine with params", "List routines"'],
  ["Email & Calendar", '"Read emails", "Send email to john@doe.com", "Show calendar", "Create meeting tomorrow 10am"'],
  ["Notes", '"Take a note: buy milk", "Read my notes"'],
  ["Reminders", '"Remind me in 10 minutes to stretch", "Remind me every day at 9 to drink water"'],
  ["Clipboard", '"What is on my clipboard", "Copy hello world to the clipboard"'],
  ["Windows", '"Switch to Chrome", "List my windows", "Show the desktop"'],
  ["System", '"Screenshot", "Lock the screen", "Battery status"'],
  ["Math", '"Calculate 12 times 8", "What is 15 percent of 240"'],
  ["Time", '"What time is it", "What is the date"'],
  ["Turkish works too", '"Chrome\'u aç", "Sesi kıs", "Panoyu oku"'],
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
async function api(path, options = {}) {
  const token = document.querySelector('meta[name="helpie-api-token"]')?.content || "";
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.headers || {}),
      "Content-Type": "application/json",
      "X-Helpie-Token": token,
    },
  });
  if (!response.ok) throw new Error("HTTP " + response.status);
  return response.json();
}

let toastTimer = null;
function toast(message) {
  const node = $("toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (node.hidden = true), 5200);
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => {
    const map = { "&": "&", "<": "<", ">": ">", '"': '"', "'": "'" };
    return map[char];
  });
}

/* ------------------------------------------------------------------ */
/*  Rendering                                                          */
/* ------------------------------------------------------------------ */
function addMessage(role, text) {
  if (!text) return;
  const row = document.createElement("div");
  row.className = "msg " + role;
  const label = role === "user" ? "You" : role === "assistant" ? "Helpie" : "Notice";
  row.innerHTML = `<div class="role">${label}</div><div class="body">${escapeHtml(text)}</div>`;
  $("messages").appendChild(row);
  $("messages").scrollTop = $("messages").scrollHeight;
}

function setStatus(value, detail) {
  const pill = $("status-pill");
  pill.className = "status-pill " + value;
  $("status-text").textContent = detail || STATUS[value] || value;
  $("mic-btn").classList.toggle("active", value === "listening" || value === "hearing");
  const chip = $("mic-chip");
  const live = value === "listening" || value === "hearing";
  chip.className = "chip " + (live ? "on" : "");
  chip.innerHTML = `<span class="dot"></span> ${live ? "Microphone: live" : "Microphone: ready"}`;
  if (value !== "idle") $("hint").hidden = true;
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("active", section.id === "view-" + view);
  });
  if (view !== "tiny") stopTinyDashboard();
  const titles = {
    chat: ["Chat", "Press Ctrl + H to speak"],
    notes: ["Notes", "Everything you asked Helpie to remember"],
    reminders: ["Reminders", "Timers that survive a restart"],
    routines: ["Routines", "Saved sequences of commands"],
    commands: ["Commands", "Examples you can say or type"],
    settings: ["Settings", "Voice, microphone and AI configuration"],
    tiny: ["Helpie", "Listening…"],
  };
  $("view-title").textContent = titles[view][0];
  $("view-sub").textContent = titles[view][1];
  document.body.classList.toggle("settings-mode", view === "settings");
  document.body.classList.toggle("tiny-mode", view === "tiny");
  if (view === "notes") {
    loadNotes();
    loadMemory();
  }
  if (view === "reminders") loadReminders();
  if (view === "routines") {
    loadRoutines();
    loadTemplates();
  }
  if (view === "settings") {
    setSettingsPage(state.settingsPage || "general");
    refreshNav();
  }
  if (view === "tiny") {
    startTinyDashboard();
  }
}

let tinyTimer = null;
let tinyTick = 0;
function startTinyDashboard() {
  if (tinyTimer) clearInterval(tinyTimer);
  tinyTick = 0;
  updateTinyTime();
  tinyTimer = setInterval(() => {
    tinyTick += 1;
    updateTinyTime();
    if (tinyTick % 60 === 0) {
      loadTinyWeather();
      loadTinyReminder();
    }
  }, 1000);
}

function stopTinyDashboard() {
  if (tinyTimer) {
    clearInterval(tinyTimer);
    tinyTimer = null;
  }
  state._tinyLoaded = false;
}

function updateTinyTime() {
  const now = new Date();
  const timeNode = $("tiny-time");
  const dateNode = $("tiny-date");
  if (timeNode) timeNode.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (dateNode) dateNode.textContent = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

function loadTinyWeather() {
  const node = $("tiny-weather-widget");
  const valueNode = $("tiny-weather");
  if (!node || !valueNode) return;
  const weather = (state.settings && state.settings.weather) || "";
  if (weather) {
    // "Denizli, TR: Clear, 15°C" -> "Clear, 15°C" so it fits the small widget.
    const short = weather.includes(":") ? weather.slice(weather.lastIndexOf(":") + 1).trim() : weather;
    node.hidden = false;
    valueNode.textContent = short || weather;
    valueNode.title = weather;
  } else {
    node.hidden = true;
  }
}

function loadTinyReminder() {
  const node = $("tiny-reminder-widget");
  const textNode = $("tiny-reminder-text");
  const timeNode = $("tiny-reminder-time");
  if (!node || !textNode || !timeNode) return;
  const items = state.reminders || [];
  const now = new Date();
  const upcoming = items.find((item) => new Date(item.due) > now);
  if (upcoming) {
    node.hidden = false;
    textNode.textContent = upcoming.text;
    const due = new Date(upcoming.due);
    timeNode.textContent = due.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } else {
    node.hidden = true;
  }
}

function setSettingsPage(page) {
  if (!SETTINGS_PAGES[page]) page = "general";
  state.settingsPage = page;

  document.querySelectorAll(".settings-page").forEach((section) => {
    section.classList.toggle("active", section.dataset.page === page);
  });
  document.querySelectorAll(".settings-nav-item[data-page]").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === page);
  });

  const trail = SETTINGS_PAGES[page];
  if (trail[0] === "AI Providers") {
    const group = $("group-providers");
    if (group) group.classList.add("expanded");
  }
  $("settings-crumb").innerHTML = `<span>Settings</span>` + trail.map((part, index) => {
    const leaf = index === trail.length - 1 ? "leaf" : "";
    return `<span class="sep">›</span><span class="${leaf}">${escapeHtml(part)}</span>`;
  }).join("");

  if (page === "plugins") renderPlugins();
  if (page === "activity") loadAudit();
}

function refreshNav() {
  const allowed = SCOPE_PAGES[state.scope];
  const query = $("settings-search").value.trim().toLowerCase();
  document.querySelectorAll(".settings-nav-item[data-page]").forEach((item) => {
    const inScope = !allowed || allowed.includes(item.dataset.page);
    const matches = !query || item.textContent.toLowerCase().includes(query);
    item.style.display = inScope && matches ? "" : "none";
  });
  document.querySelectorAll(".settings-group").forEach((group) => {
    const visible = Array.from(group.querySelectorAll("[data-page]"))
      .some((item) => item.style.display !== "none");
    group.style.display = visible ? "" : "none";
    if (query && visible) group.classList.add("expanded");
  });
}

function renderCommands() {
  $("cmd-grid").innerHTML = COMMANDS.map(([title, examples]) =>
    `<div class="cmd"><b>${escapeHtml(title)}</b><span>${escapeHtml(examples)}</span></div>`
  ).join("");
}

async function loadNotes() {
  try {
    const data = await api("/api/notes");
    const list = data.notes || [];
    $("note-list").innerHTML = list.length
      ? list.map((note) => `<div class="note"><time>${escapeHtml(note.time || "")}</time><span>${escapeHtml(note.text)}</span></div>`).join("")
      : `<div class="empty">No notes yet. Say "take a note: ..." and it will show up here.</div>`;
  } catch (error) {
    toast("Could not load notes.");
  }
}

function renderMemory(items) {
  if (items) state.memory = items;
  const node = $("memory-list");
  if (!node) return;
  const list = state.memory || [];
  if (!list.length) {
    node.innerHTML = `<div class="empty">Nothing remembered yet. Say "remember that I ..." and it stays here.</div>`;
    return;
  }
  node.innerHTML = list.map((item) => (
    `<div class="note"><time>${escapeHtml((item.time || "").replace("T", " "))}</time>` +
    `<span>${escapeHtml(item.text)}</span>` +
    `<button class="mini del" data-memory="${escapeHtml(item.text)}">Forget</button></div>`
  )).join("");
  node.querySelectorAll("[data-memory]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api("/api/memory/delete", { method: "POST", body: JSON.stringify({ text: button.dataset.memory }) });
      } catch (error) {
        toast("Could not forget that.");
      }
    });
  });
}

async function loadMemory() {
  try {
    const data = await api("/api/memory");
    renderMemory(data.memory || []);
  } catch (error) {
    toast("Could not load your memory.");
  }
}

/* ------------------------------------------------------------------ */
/*  Reminders                                                          */
/* ------------------------------------------------------------------ */
function renderReminders(items) {
  if (items) state.reminders = items;
  const list = state.reminders || [];
  const node = $("reminder-list");
  if (!node) return;
  if (!list.length) {
    node.innerHTML = `<div class="empty">No reminders yet. Say "remind me in 10 minutes to stretch".</div>`;
    return;
  }
  node.innerHTML = list.map((reminder) => {
    let when = reminder.due || "";
    try {
      when = new Date(reminder.due).toLocaleString(undefined, {
        weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
      });
    } catch (error) { /* keep raw text */ }
    const repeat = reminder.repeat && reminder.repeat !== "none" ? ` · ${reminder.repeat}` : "";
    return `<div class="note"><time>${escapeHtml(when)}${escapeHtml(repeat)}</time>` +
      `<span>${escapeHtml(reminder.text)}</span>` +
      `<button class="mini del" data-reminder="${escapeHtml(reminder.id)}">Delete</button></div>`;
  }).join("");
  node.querySelectorAll("[data-reminder]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api("/api/reminders/delete", { method: "POST", body: JSON.stringify({ id: button.dataset.reminder }) });
      } catch (error) {
        toast("Could not delete that reminder.");
      }
    });
  });
}

async function loadReminders() {
  try {
    const data = await api("/api/reminders");
    renderReminders(data.reminders || []);
  } catch (error) {
    toast("Could not load reminders.");
  }
}

/* ------------------------------------------------------------------ */
/*  Microphone test                                                    */
/* ------------------------------------------------------------------ */
function showMicResult(result) {
  const verdicts = {
    good: "Good — the microphone is picking up your voice.",
    low: "Very quiet. Move closer or raise the input level in Windows.",
    silent: "No sound at all. Unmute the mic or pick another device.",
    "no-device": "Could not open the microphone. Check that it is connected.",
  };
  const node = $("mic-verdict");
  node.textContent = verdicts[result.verdict] || "Test finished.";
  node.className = "mic-verdict " + (result.verdict || "");
  $("level-fill").style.width = Math.round((result.peak || 0) * 100) + "%";
}

async function testMic() {
  if (state.micTesting) return;
  state.micTesting = true;
  const button = $("test-mic");
  button.disabled = true;
  button.textContent = "Listening…";
  $("mic-verdict").textContent = "Speak now…";
  $("mic-verdict").className = "mic-verdict";
  $("level-fill").style.width = "0%";
  try {
    const result = await api("/api/mic/test", { method: "POST", body: JSON.stringify({ seconds: 4 }) });
    showMicResult(result);
  } catch (error) {
    toast("Could not test microphone.");
  } finally {
    state.micTesting = false;
    button.disabled = false;
    button.textContent = "Test mic";
  }
}

/* ------------------------------------------------------------------ */
/*  Chat                                                               */
/* ------------------------------------------------------------------ */
async function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || state.busy) return;
  input.value = "";
  input.style.height = "auto";
  state.busy = true;
  try {
    await api("/api/ask", { method: "POST", body: JSON.stringify({ text }) });
  } catch (error) {
    toast("Could not reach Helpie's brain.");
    setStatus("idle");
  } finally {
    state.busy = false;
  }
}

async function startListening() {
  try {
    await api("/api/listen", { method: "POST", body: "{}" });
  } catch (error) {
    toast("Could not start the microphone.");
  }
}

function showChat(chat) {
  state.currentChat = chat.id;
  $("messages").innerHTML = "";
  (chat.messages || []).forEach((msg) => addMessage(msg.role, msg.text));
  setStatus("idle");
  const requested = new URLSearchParams(location.search).get("view");
  if (requested && document.getElementById("view-" + requested)) setView(requested);
  else setView("chat");
}

async function newChat() {
  state.currentChat = null;
  setView("chat");
  $("input").focus();
  try {
    const data = await api("/api/new_chat", { method: "POST", body: "{}" });
    if (data.chat) state.currentChat = data.chat.id;
  } catch (error) {
    toast("Could not start a new chat.");
  }
}

/* ------------------------------------------------------------------ */
/*  History                                                            */
/* ------------------------------------------------------------------ */
function renderRecent(chats) {
  if (chats) state.chats = chats;
  const node = $("recent");
  if (!node) return;
  if (!state.chats.length) {
    node.innerHTML = `<div class="recent-empty">No chats yet</div>`;
    return;
  }
  node.innerHTML = state.chats.map((chat) => {
    const preview = (chat.messages?.[0]?.text || "").slice(0, 40);
    const active = state.currentChat === chat.id ? "active" : "";
    return `<button class="recent-item ${active}" data-id="${chat.id}">` +
      `<span class="recent-title">${escapeHtml(preview || "New chat")}</span>` +
      `<span class="recent-del" title="Delete">×</span></button>`;
  }).join("");
  node.querySelectorAll(".recent-item").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const chat = await api("/api/history/select", { method: "POST", body: JSON.stringify({ id: btn.dataset.id }) });
      if (chat) showChat(chat);
    });
    btn.querySelector(".recent-del").addEventListener("click", (e) => {
      e.stopPropagation();
      api("/api/history/delete", { method: "POST", body: JSON.stringify({ id: btn.dataset.id }) });
    });
  });
}

/* ------------------------------------------------------------------ */
/*  Settings                                                           */
/* ------------------------------------------------------------------ */
function fillSelect(select, items, value, labelKey, valueKey) {
  select.innerHTML = "";
  items.forEach((item) => {
    const option = document.createElement("option");
    option.value = item[valueKey];
    option.textContent = item[labelKey];
    select.appendChild(option);
  });
  if (value !== null && value !== undefined) select.value = String(value);
}

function applySettings() {
  const s = state.settings || {};

  fillSelect($("set-mic"), [{ index: "", name: "System default" }, ...state.mics],
    s.mic_index === null || s.mic_index === undefined ? "" : s.mic_index, "name", "index");
  fillSelect($("set-voice"), state.voices, s.voice, "label", "id");
  fillSelect($("set-language"), state.languages, s.language, "label", "id");

  $("set-name").value = s.user_name || "";
  $("set-city").value = s.city || "";
  $("set-theme").value = s.theme || "dark";
  var themeClass = "theme-" + (s.theme || "dark");
  document.body.className = themeClass;
  document.documentElement.className = themeClass;
  $("set-rate").value = s.rate || "+0%";
  $("set-cloud-transcription").checked = !!s.cloud_speech_consent;
  $("set-cloud-tts").checked = !!s.cloud_tts_consent;
  $("set-autolisten").checked = !!s.auto_listen;
  $("set-continuous").checked = !!s.continuous;
  $("set-updates").checked = !!s.check_updates;
  $("set-background").checked = s.background_apps !== false;
  $("set-wake-word").checked = !!s.wake_word;
  $("set-autostart").checked = !!s.autostart;

  // Voice settings
  $("set-voice").value = s.voice || "";
  $("set-language").value = s.language || "";
  $("set-rate").value = s.rate || "+0%";

  // Wake word
  $("set-wake-word").checked = !!s.wake_word;
  const hasWakeWordKey = !!s.has_wake_word_key;
  $("porcupine-key-state").textContent = hasWakeWordKey ? "connected" : "not set";
  $("porcupine-key-state").className = "badge" + (hasWakeWordKey ? " has-key" : "");

  // AI Providers
  $("set-key").value = "";
  $("key-state").textContent = s.has_key ? "connected (" + s.key_hint + ")" : "not set";
  $("key-state").className = "badge" + (s.has_key ? " has-key" : "");
  $("model-chip").className = "chip " + (s.has_key ? "on" : "off");
  $("model-chip").innerHTML = `<span class="dot"></span> AI: ${s.has_key ? "Gemini connected" : "commands only"}`;

  // Ollama settings
  $("set-ollama-url").value = s.ollama_url || "http://localhost:11434";
  $("set-ollama-model").value = s.ollama_model || "llama3.2";

  // OpenAI-compatible settings
  $("set-openai-url").value = s.openai_url || "";
  $("set-openai-key").value = "";
  $("set-openai-model").value = s.openai_model || "";
  const openaiState = $("openai-key-state");
  if (openaiState) {
    openaiState.textContent = s.has_openai_key ? "connected (" + s.openai_key_hint + ")" : "not set";
    openaiState.className = "badge" + (s.has_openai_key ? " has-key" : "");
  }

  // Plugins
  renderPlugins();
}

async function saveSettings() {
  const mic = $("set-mic").value;
  const patch = {
    // General
    user_name: $("set-name").value.trim(),
    city: $("set-city").value.trim(),
    theme: $("set-theme").value,
    auto_listen: $("set-autolisten").checked,
    continuous: $("set-continuous").checked,
    check_updates: $("set-updates").checked,
    background_apps: $("set-background").checked,
    autostart: $("set-autostart").checked,
    // Voice
    mic_index: mic === "" ? null : Number(mic),
    language: $("set-language").value,
    voice: $("set-voice").value,
    rate: $("set-rate").value,
    cloud_speech_consent: $("set-cloud-transcription").checked,
    cloud_tts_consent: $("set-cloud-tts").checked,
    // Wake word
    wake_word: $("set-wake-word").checked,
    wake_word_access_key: $("set-porcupine-key").value.trim() || undefined,
    // AI providers
    api_key: $("set-key").value.trim() || undefined,
    ollama_url: $("set-ollama-url").value.trim() || "http://localhost:11434",
    ollama_model: $("set-ollama-model").value.trim() || "llama3.2",
    openai_url: $("set-openai-url").value.trim() || undefined,
    openai_key: $("set-openai-key").value.trim() || undefined,
    openai_model: $("set-openai-model").value.trim() || undefined,
  };
  try {
    const data = await api("/api/settings", { method: "POST", body: JSON.stringify(patch) });
    state.settings = data.settings;
    $("set-key").value = "";
    $("set-porcupine-key").value = "";
    $("set-openai-key").value = "";
    applySettings();
    const hint = $("settings-saved");
    hint.textContent = "Saved.";
    hint.style.color = "var(--green)";
    setTimeout(() => {
      hint.textContent = "Changes apply when you save.";
      hint.style.color = "";
    }, 2600);
    toast("Settings saved.");
  } catch (error) {
    toast("Could not save settings.");
  }
}

/* ------------------------------------------------------------------ */
/*  Plugins                                                            */
/* ------------------------------------------------------------------ */
async function renderPlugins() {
  const container = $("plugins-list");
  if (!container) return;
  try {
    const data = await api("/api/plugins");
    let plugins = data.plugins || [];
    if (state.pluginFilter === "on") plugins = plugins.filter((p) => p.enabled);
    if (state.pluginFilter === "off") plugins = plugins.filter((p) => !p.enabled);
    if (!plugins.length) {
      const empty = state.pluginFilter === "all" ? "No plugins found." : "No plugins match this filter.";
      container.innerHTML = `<div class="plugin-empty">${empty}</div>`;
      return;
    }
    container.innerHTML = plugins.map((p) => `
      <div class="plugin-card ${p.enabled ? "on" : ""}">
        <div class="plugin-header">
          <div class="plugin-title">
            <strong>${escapeHtml(p.display_name || p.name)}</strong>
            <span class="plugin-version">v${escapeHtml(p.version)}</span>
            ${p.error ? `<span class="badge">${p.trusted ? "error" : "blocked"}</span>` : ""}
          </div>
          <label class="switch" title="Enable or disable">
            <input type="checkbox" data-enable="${escapeHtml(p.name)}" ${p.enabled ? "checked" : ""} ${p.trusted ? "" : "disabled"} />
            <span class="track"></span>
          </label>
        </div>
        <p class="plugin-desc">${escapeHtml(p.description)}</p>
        <div class="plugin-commands">
          <strong>Commands:</strong>
          ${(p.commands || []).length
            ? p.commands.map((command) => `<code>${escapeHtml(command)}</code>`).join(" ")
            : `<span class="muted">none</span>`}
        </div>
        ${p.error ? `<div class="plugin-error">${escapeHtml(p.error)}</div>` : ""}
        <div class="plugin-actions">
          <button class="ghost" data-configure="${escapeHtml(p.name)}" ${p.trusted ? "" : "disabled"}>Configure</button>
          <button class="ghost" data-reload="${escapeHtml(p.name)}" ${p.trusted ? "" : "disabled"}>Reload</button>
        </div>
        <div class="plugin-config" id="config-${escapeHtml(p.name)}" hidden></div>
      </div>
    `).join("");

    container.querySelectorAll("[data-enable]").forEach((input) => {
      input.addEventListener("change", async () => {
        const name = input.dataset.enable;
        if (input.checked && !window.confirm(
          "This plugin is not sandboxed and can access files and network resources as Helpie. Enable it only if you trust its code. Continue?"
        )) {
          input.checked = false;
          return;
        }
        const path = input.checked ? "/api/plugins/load" : "/api/plugins/unload";
        try {
          await api(path, { method: "POST", body: JSON.stringify({ name }) });
          renderPlugins();
        } catch (error) {
          input.checked = !input.checked;
          toast("Could not toggle that plugin.");
        }
      });
    });
    container.querySelectorAll("[data-reload]").forEach((button) => {
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api("/api/plugins/reload", { method: "POST", body: JSON.stringify({ name: button.dataset.reload }) });
          toast("Plugin reloaded.");
          renderPlugins();
        } catch (error) {
          button.disabled = false;
          toast("Could not reload that plugin.");
        }
      });
    });
    container.querySelectorAll("[data-configure]").forEach((button) => {
      button.addEventListener("click", () => togglePluginConfig(button.dataset.configure));
    });
  } catch (error) {
    container.innerHTML = `<div class="plugin-empty">Could not load plugins.</div>`;
  }
}

async function togglePluginConfig(name) {
  const node = $("config-" + name);
  if (!node) return;
  if (!node.hidden) { node.hidden = true; return; }
  node.hidden = false;
  if (node.dataset.loaded === "1") return;
  node.innerHTML = `<div class="plugin-empty">Loading settings…</div>`;
  try {
    const data = await api("/api/plugins/settings", { method: "POST", body: JSON.stringify({ name, get: true }) });
    const schema = data.schema || {};
    const values = data.settings || {};
    const configured = data.configured || {};
    const keys = Object.keys(schema);
    if (!keys.length) {
      node.innerHTML = `<div class="plugin-empty">This plugin has no settings.</div>`;
      node.dataset.loaded = "1";
      return;
    }
    node.innerHTML = keys.map((key) => {
      const item = schema[key] || {};
      const label = key.replace(/_/g, " ");
      const desc = item.description ? `<span class="field-desc">${escapeHtml(item.description)}</span>` : "";
      const secret = /key|secret|token|password/i.test(key);
      const current = secret ? "" : (values[key] !== undefined ? values[key] : (item.default !== undefined ? item.default : ""));
      let control;
      if (item.type === "boolean") {
        control = `<label class="switch"><input type="checkbox" data-key="${escapeHtml(key)}" ${current ? "checked" : ""} /><span class="track"></span></label>`;
      } else {
        const type = item.type === "number" ? "number" : secret ? "password" : "text";
        const placeholder = secret && configured[key] ? "Saved — enter a new value to replace" : String(item.default === undefined ? "" : item.default);
        control = `<input type="${type}" data-key="${escapeHtml(key)}" value="${escapeHtml(String(current))}" placeholder="${escapeHtml(placeholder)}" />`;
      }
      return `<div class="field-row">` +
        `<div class="field-text"><span class="field-label">${escapeHtml(label)}</span>${desc}</div>` +
        `<div class="field-control">${control}</div></div>`;
    }).join("") +
      `<div class="plugin-config-foot"><button class="ghost" data-save-config="${escapeHtml(name)}">Save settings</button></div>`;

    node.dataset.loaded = "1";
    node.querySelector("[data-save-config]").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = "Saving…";
      try {
        const fields = node.querySelectorAll("[data-key]");
        for (const field of fields) {
          if (field.type === "password" && !field.value) continue;
          const value = field.type === "checkbox" ? field.checked : field.value;
          await api("/api/plugins/settings", { method: "POST", body: JSON.stringify({ name, key: field.dataset.key, value }) });
        }
        await api("/api/plugins/reload", { method: "POST", body: JSON.stringify({ name }) });
        toast("Plugin settings saved.");
      } catch (error) {
        toast("Could not save plugin settings.");
      }
      button.disabled = false;
      button.textContent = "Save settings";
    });
  } catch (error) {
    node.innerHTML = `<div class="plugin-empty">Could not load plugin settings.</div>`;
  }
}

async function reloadAllPlugins() {
  const button = $("plugins-reload");
  button.disabled = true;
  try {
    const data = await api("/api/plugins");
    for (const plugin of (data.plugins || []).filter((item) => item.enabled)) {
      await api("/api/plugins/reload", { method: "POST", body: JSON.stringify({ name: plugin.name }) });
    }
    toast("All plugins reloaded.");
    renderPlugins();
  } catch (error) {
    toast("Could not reload plugins.");
  }
  button.disabled = false;
}
  /* ------------------------------------------------------------------ */
/*  Updates                                                            */
/* ------------------------------------------------------------------ */
async function checkUpdates(manual = false) {
  try {
    const data = await api("/api/update/check");
    if (data.available) {
      state.update = data;
      $("update-banner-text").textContent = `Helpie ${data.version} is available (you have ${data.current}).`;
      $("update-banner").hidden = false;
    } else if (manual) {
      toast("You are on the latest version.");
    }
  } catch (error) {
    if (manual) toast("Could not check for updates.");
  }
}

async function installUpdate() {
  if (!state.update) return;
  try {
    const result = await api("/api/update/apply", { method: "POST", body: JSON.stringify({ url: state.update.url }) });
    if (result.ok) toast("Update installed. Restarting…");
  } catch (error) {
    toast("Update failed.");
  }
}

/* ------------------------------------------------------------------ */
/*  Event stream                                                       */
/* ------------------------------------------------------------------ */
function handleEvent(event) {
  switch (event.type) {
    case "message":
      addMessage(event.role, event.text);
      break;
    case "state":
      setStatus(event.value, event.detail);
      if (state.view === "tiny") initTinyView();
      break;
    case "heard":
      $("status-text").textContent = "heard: " + event.text;
      break;
    case "hint":
      $("hint").textContent = event.text;
      $("hint").hidden = false;
      break;
    case "error":
      $("hint").textContent = event.text;
      $("hint").hidden = false;
      setStatus("idle");
      break;
    case "settings":
      state.settings = event.value;
      applySettings();
      break;
    case "history":
      renderRecent(event.chats || []);
      break;
    case "reminders":
      renderReminders(event.reminders || []);
      break;
    case "memory":
      renderMemory(event.items || []);
      break;
    case "miclevel":
      $("level-fill").style.width = Math.round((event.value || 0) * 100) + "%";
      break;
    case "mictest":
      $("level-fill").style.width = "0%";
      $("mic-verdict").textContent = "Speak now…";
      break;
    case "micresult":
      showMicResult(event);
      break;
    case "update":
      state.update = event;
      $("update-banner-text").textContent = `Helpie ${event.version} is available (you have ${event.current}).`;
      $("update-banner").hidden = false;
      break;
    default:
      break;
  }
}

let tinyLoaded = false;
async function poll() {
  try {
    const data = await api("/api/events?after=" + state.lastEvent);
    (data.events || []).forEach((event) => {
      state.lastEvent = Math.max(state.lastEvent, event.id);
      handleEvent(event);
    });
    // Load tiny dashboard widgets on first successful poll
    if (state.view === "tiny" && !state._tinyLoaded) {
      state._tinyLoaded = true;
      loadTinyWeather();
      loadTinyReminder();
    }
  } catch (error) {
    /* server may be restarting */
  }
  setTimeout(poll, 400);
}

function initTinyView() {
  // Update tiny view status based on current state
  const status = state.status || "idle";
  const statusText = {
    idle: "Ready",
    listening: "Listening…",
    hearing: "Hearing you…",
    thinking: "Thinking…",
    speaking: "Speaking…",
  }[status] || "Ready";
  $("tiny-status-text").textContent = statusText;
  const dot = $("tiny-dot");
  if (status === "listening" || status === "hearing") {
    dot.style.background = "var(--accent)";
    dot.style.animation = "pulse-glow 1.2s ease-in-out infinite";
    dot.style.boxShadow = "0 0 12px var(--accent)";
  } else if (status === "thinking") {
    dot.style.background = "var(--amber)";
    dot.style.animation = "pulse-glow 1s ease-in-out infinite";
    dot.style.boxShadow = "0 0 10px var(--amber)";
  } else if (status === "speaking") {
    dot.style.background = "var(--green)";
    dot.style.animation = "pulse-glow 1.5s ease-in-out infinite";
    dot.style.boxShadow = "0 0 10px var(--green)";
  } else {
    dot.style.background = "var(--dim)";
    dot.style.animation = "none";
    dot.style.boxShadow = "none";
  }
  loadTinyWeather();
  loadTinyReminder();
}

/* ------------------------------------------------------------------ */
/*  Activity (audit log)                                               */
/* ------------------------------------------------------------------ */
function formatAuditTime(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso || "");
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const now = new Date();
  if (date.toDateString() === now.toDateString()) return time;
  return date.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + time;
}

function renderAudit(data) {
  const node = $("audit-list");
  if (!node) return;
  const entries = (data && data.entries) || [];
  const stats = (data && data.stats) || { count: 0, by_source: {} };
  const summary = $("audit-summary");
  if (summary) {
    const parts = Object.entries(stats.by_source || {}).map(([key, value]) => `${value} ${key}`);
    summary.textContent = entries.length ? `${stats.count} logged actions · ${parts.join(" · ")}` : "";
  }
  if (!entries.length) {
    node.innerHTML = `<div class="audit-empty">Nothing logged yet. Ask Helpie to open an app, take a screenshot or run a routine.</div>`;
    return;
  }
  node.innerHTML = entries.map((entry) =>
    `<div class="audit-row${entry.ok ? "" : " failed"}">` +
    `<span class="audit-time">${escapeHtml(formatAuditTime(entry.ts))}</span>` +
    `<span class="audit-dot ${escapeHtml(entry.source || "action")}"></span>` +
    `<span class="audit-action">${escapeHtml(entry.action)}</span>` +
    `<span class="audit-detail">${escapeHtml(entry.detail || "")}</span>` +
    `</div>`).join("");
}

async function loadAudit() {
  const node = $("audit-list");
  if (!node) return;
  if (!node.dataset.loaded) node.innerHTML = `<div class="audit-empty">Loading…</div>`;
  try {
    const query = state.auditSource ? "?source=" + encodeURIComponent(state.auditSource) : "";
    renderAudit(await api("/api/audit" + query));
    node.dataset.loaded = "1";
  } catch (error) {
    node.innerHTML = `<div class="audit-empty">Could not load the activity log.</div>`;
  }
}

/* ------------------------------------------------------------------ */
/*  Routines                                                           */
/* ------------------------------------------------------------------ */
function describeStep(step) {
  const action = step.action || "";
  const args = step.args || {};
  const text = args.app || args.text || "";
  switch (action) {
    case "open_app": return "Open " + (text || "an app");
    case "close_app": return "Close " + (text || "an app");
    case "web_search": return "Search the web for " + (args.query || text);
    case "open_site": return "Open " + (args.name || text);
    case "set_volume": return "Set volume to " + args.percent + "%";
    case "volume": return "Volume " + (args.direction || "change");
    case "set_brightness": return "Set brightness to " + args.percent + "%";
    case "brightness": return "Brightness " + (args.direction || "change");
    case "what_time": return "Tell the time";
    case "screenshot": return "Take a screenshot";
    case "lock_screen": return "Lock the screen";
    case "add_note": return "Take a note: " + text;
    case "set_timer": return "Remind in " + args.minutes + " min: " + (args.label || "timer");
    case "speak": return "Say: " + text;
    case "wait": return "Wait " + args.seconds + "s";
    default: {
      const extra = Object.values(args).filter(Boolean).join(" · ");
      return (action || "step").replace(/_/g, " ") + (extra ? " — " + extra : "");
    }
  }
}

function renderRoutines(items) {
  if (items) state.routines = items;
  const node = $("routine-list");
  if (!node) return;
  const list = state.routines || [];
  if (!list.length) {
    node.innerHTML = `<div class="empty">No routines yet. Create one above, or say “save routine morning with steps open chrome and then what time is it”.</div>`;
    return;
  }
  node.innerHTML = list.map((routine) => {
    const steps = (routine.steps || []).map((step, index) =>
      `<li><span class="n">${index + 1}.</span><span>${escapeHtml(describeStep(step))}</span></li>`).join("");
    return `<div class="routine-card">` +
      `<div class="routine-head"><div>` +
      `<div class="routine-name">${escapeHtml(routine.name)}</div>` +
      `${routine.description ? `<div class="routine-desc">${escapeHtml(routine.description)}</div>` : ""}` +
      `</div></div>` +
      `<ol class="routine-steps">${steps}</ol>` +
      `<div class="routine-actions">` +
      `<button class="ghost" data-run="${escapeHtml(routine.name)}">Run</button>` +
      `<button class="ghost" data-delete="${escapeHtml(routine.name)}">Delete</button>` +
      `</div>` +
      `<div class="routine-result" id="routine-result" hidden></div>` +
      `</div>`;
  }).join("");

  node.querySelectorAll("[data-run]").forEach((button) => {
    button.addEventListener("click", async () => {
      const name = button.dataset.run;
      button.disabled = true;
      button.textContent = "Running…";
      const result = await runRoutine(name);
      button.disabled = false;
      button.textContent = "Run";
      const box = button.closest(".routine-card").querySelector(".routine-result");
      if (box) {
        box.hidden = false;
        box.textContent = result;
      }
    });
  });
  node.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api("/api/routines/delete", { method: "POST", body: JSON.stringify({ name: button.dataset.delete }) });
        toast("Routine deleted.");
        loadRoutines();
      } catch (error) {
        toast("Could not delete that routine.");
      }
    });
  });
}

async function loadRoutines() {
  try {
    const data = await api("/api/routines");
    renderRoutines(data.routines || []);
  } catch (error) {
    toast("Could not load routines.");
  }
}

async function runRoutine(name) {
  try {
    const data = await api("/api/ask", { method: "POST", body: JSON.stringify({ text: "run " + name }) });
    return data.reply || "Done.";
  } catch (error) {
    return "Could not run that routine.";
  }
}

async function loadTemplates() {
  const node = $("template-list");
  if (!node) return;
  try {
    const data = await api("/api/routines/templates");
    const templates = data.templates || {};
    const entries = Object.entries(templates);
    if (!entries.length) {
      node.innerHTML = `<span class="muted">No templates available.</span>`;
      return;
    }
    node.innerHTML = entries.map(([key, tpl]) =>
      `<button class="tpl-chip" data-template="${escapeHtml(key)}">` +
      `<span>${escapeHtml(key.replace(/_/g, " "))}</span>` +
      `<small>${escapeHtml(tpl.description || "")} · ${(tpl.steps || []).length} steps</small></button>`).join("");
    node.querySelectorAll("[data-template]").forEach((button) => {
      button.addEventListener("click", async () => {
        const template = templates[button.dataset.template];
        button.disabled = true;
        try {
          await api("/api/routines/save", {
            method: "POST",
            body: JSON.stringify({ name: button.dataset.template, description: template.description, steps: template.steps }),
          });
          toast("Template added.");
          loadRoutines();
        } catch (error) {
          toast("Could not add that template.");
        }
        button.disabled = false;
      });
    });
  } catch (error) {
    node.innerHTML = `<span class="muted">Templates unavailable.</span>`;
  }
}

function initRoutineForm() {
  $("routine-new").addEventListener("click", () => {
    $("routine-form").hidden = false;
    $("routine-name").focus();
  });
  $("routine-cancel").addEventListener("click", () => {
    $("routine-form").hidden = true;
  });
  $("routines-refresh").addEventListener("click", () => {
    loadRoutines();
    loadTemplates();
  });
  $("routine-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const name = $("routine-name").value.trim().toLowerCase().replace(/[^a-z0-9_]+/g, "_");
    const description = $("routine-desc").value.trim();
    const steps = $("routine-steps").value.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!name) {
      toast("Give the routine a name.");
      return;
    }
    if (!steps.length) {
      toast("Add at least one step.");
      return;
    }
    try {
      const data = await api("/api/ask", {
        method: "POST",
        body: JSON.stringify({ text: "save routine " + name + " with steps " + steps.join(" and then ") }),
      });
      if (description) {
        const list = await api("/api/routines");
        const created = (list.routines || []).find((item) => item.name === name);
        if (created) {
          await api("/api/routines/save", {
            method: "POST",
            body: JSON.stringify({ name, description, steps: created.steps }),
          });
        }
      }
      toast(data.reply || "Routine saved.");
      $("routine-form").hidden = true;
      $("routine-name").value = "";
      $("routine-desc").value = "";
      $("routine-steps").value = "";
      loadRoutines();
    } catch (error) {
      toast("Could not save the routine.");
    }
  });
}

/* ------------------------------------------------------------------ */
/*  Command palette                                                    */
/* ------------------------------------------------------------------ */
const NAV_VIEWS = [
  ["chat", "Go to Chat"],
  ["notes", "Go to Notes & Memory"],
  ["reminders", "Go to Reminders"],
  ["routines", "Go to Routines"],
  ["commands", "Go to Commands"],
  ["settings", "Go to Settings"],
];

const QUICK_ACTIONS = [
  "Screenshot",
  "Lock the screen",
  "Mute",
  "Volume up",
  "Volume down",
  "Volume 40",
  "Brightness up",
  "Brightness down",
  "What time is it",
  "Battery status",
  "Good morning",
  "Give me a briefing",
  "Read my notes",
  "Clipboard history",
  "System stats",
  "List my windows",
  "Show the desktop",
  "Organize downloads by type",
];

let paletteItems = [];
let paletteShown = [];
let paletteIndex = 0;

function paletteScore(label, query) {
  const text = label.toLowerCase();
  if (!query) return 1;
  if (text.startsWith(query)) return 4;
  if (text.includes(query)) return 3;
  let index = 0;
  for (const char of text) {
    if (char === query[index]) index += 1;
    if (index === query.length) return 2;
  }
  return 0;
}

async function runAsk(text) {
  setView("chat");
  try {
    await api("/api/ask", { method: "POST", body: JSON.stringify({ text }) });
  } catch (error) {
    toast("Could not reach Helpie's brain.");
  }
}

async function paletteBuild() {
  let routines = [];
  try {
    const data = await api("/api/routines");
    routines = data.routines || [];
  } catch (error) {
    routines = [];
  }

  const items = [];
  for (const [view, label] of NAV_VIEWS) {
    items.push({ group: "Go", label, hint: "go", run: () => setView(view) });
  }
  for (const action of QUICK_ACTIONS) {
    items.push({ group: "Action", label: action, hint: "run", run: () => runAsk(action) });
  }
  for (const routine of routines) {
    items.push({
      group: "Routine",
      label: "Run " + routine.name,
      hint: (routine.steps || []).length + " steps",
      run: () => runAsk("run " + routine.name),
    });
  }
  for (const [page, trail] of Object.entries(SETTINGS_PAGES)) {
    items.push({
      group: "Settings",
      label: trail.join(" › "),
      hint: "open",
      run: () => {
        setView("settings");
        setSettingsPage(page);
      },
    });
  }
  for (const chat of (state.chats || []).slice(0, 8)) {
    const preview = (chat.messages && chat.messages[0] && chat.messages[0].text) || "New chat";
    items.push({
      group: "Chat",
      label: preview.slice(0, 48),
      hint: "open",
      run: async () => {
        const selected = await api("/api/history/select", { method: "POST", body: JSON.stringify({ id: chat.id }) });
        if (selected) showChat(selected);
      },
    });
  }
  paletteItems = items;
}

function paletteRender() {
  const node = $("palette-list");
  const query = $("palette-input").value.trim().toLowerCase();
  paletteShown = paletteItems
    .map((item) => ({ item, score: paletteScore(item.label, query) }))
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 40)
    .map((entry) => entry.item);

  if (!paletteShown.length) {
    node.innerHTML = `<div class="palette-empty">Nothing matches “${escapeHtml(query)}”.</div>`;
    return;
  }
  if (paletteIndex >= paletteShown.length) paletteIndex = 0;

  node.innerHTML = paletteShown.map((item, index) =>
    `<button class="palette-item ${index === paletteIndex ? "active" : ""}" data-index="${index}">` +
    `<span class="p-group">${escapeHtml(item.group)}</span>` +
    `<span class="p-label">${escapeHtml(item.label)}</span>` +
    `<span class="p-hint">${escapeHtml(item.hint || "")}</span></button>`).join("");

  node.querySelectorAll(".palette-item").forEach((button) => {
    button.addEventListener("click", () => paletteRun(paletteShown[Number(button.dataset.index)]));
  });
  const active = node.querySelector(".palette-item.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

async function paletteOpen() {
  $("palette").hidden = false;
  $("palette-input").value = "";
  paletteIndex = 0;
  $("palette-list").innerHTML = `<div class="palette-empty">Loading…</div>`;
  $("palette-input").focus();
  await paletteBuild();
  paletteRender();
}

function paletteClose() {
  $("palette").hidden = true;
  $("palette-input").value = "";
}

async function paletteRun(item) {
  if (!item) return;
  paletteClose();
  try {
    await item.run();
  } catch (error) {
    toast("Could not run that.");
  }
}

/* ------------------------------------------------------------------ */
/*  Wiring                                                             */
/* ------------------------------------------------------------------ */
function bind() {
  const tinyClose = $("tiny-close");
  if (tinyClose) {
    tinyClose.addEventListener("click", () => {
      api("/api/window", { method: "POST", body: JSON.stringify({ target: "hide-tiny" }) }).catch(() => {});
    });
  }
  const tinyMain = $("tiny-open-main");
  if (tinyMain) {
    tinyMain.addEventListener("click", () => {
      api("/api/window", { method: "POST", body: JSON.stringify({ target: "full" }) }).catch(() => {});
    });
  }
  $("send-btn").addEventListener("click", send);
  $("input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  });
  $("input").addEventListener("input", (event) => {
    const field = event.target;
    field.style.height = "auto";
    field.style.height = Math.min(field.scrollHeight, 140) + "px";
  });

  $("mic-btn").addEventListener("click", startListening);
  $("new-chat").addEventListener("click", newChat);

  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => setView(item.dataset.view));
  });

  // Settings navigation
  document.querySelectorAll(".settings-nav-item[data-page]").forEach((item) => {
    item.addEventListener("click", () => setSettingsPage(item.dataset.page));
  });
  document.querySelectorAll("[data-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = $("group-" + button.dataset.toggle);
      if (group) group.classList.toggle("expanded");
    });
  });
  $("settings-close").addEventListener("click", () => setView("chat"));
  $("settings-scope").addEventListener("change", (event) => {
    state.scope = event.target.value;
    refreshNav();
    const allowed = SCOPE_PAGES[state.scope];
    if (allowed && !allowed.includes(state.settingsPage)) setSettingsPage(allowed[0]);
  });
  $("settings-search").addEventListener("input", refreshNav);
  $("set-theme").addEventListener("change", async () => {
    document.body.className = "";
    document.body.classList.add("theme-" + $("set-theme").value);
    state.theme = $("set-theme").value;
    try {
      await api("/api/settings", { method: "POST", body: JSON.stringify({ theme: $("set-theme").value }) });
    } catch (error) {
      toast("Could not save theme.");
    }
  });
  $("nav-update").addEventListener("click", () => checkUpdates(true));
  $("nav-github").addEventListener("click", () => {
    window.open("https://github.com/Flynntaggart26/helpie", "_blank");
  });
  $("nav-quit").addEventListener("click", () => api("/api/quit", { method: "POST", body: "{}" }));
  document.querySelectorAll("#plugin-filter .seg-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.pluginFilter = button.dataset.filter;
      document.querySelectorAll("#plugin-filter .seg-item").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      renderPlugins();
    });
  });
  $("plugins-reload").addEventListener("click", reloadAllPlugins);
  document.querySelectorAll("#audit-filter .seg-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.auditSource = button.dataset.source || "";
      document.querySelectorAll("#audit-filter .seg-item").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      loadAudit();
    });
  });
  $("audit-refresh").addEventListener("click", () => {
    delete $("audit-list").dataset.loaded;
    loadAudit();
  });
  $("audit-clear").addEventListener("click", async () => {
    try {
      await api("/api/audit/clear", { method: "POST", body: "{}" });
      delete $("audit-list").dataset.loaded;
      loadAudit();
      toast("Activity log cleared.");
    } catch (error) {
      toast("Could not clear the activity log.");
    }
  });
  $("about-update").addEventListener("click", () => checkUpdates(true));
  $("about-github").addEventListener("click", () => {
    window.open("https://github.com/Flynntaggart26/helpie", "_blank");
  });
  $("get-ollama").addEventListener("click", (event) => {
    event.preventDefault();
    window.open("https://ollama.com/download", "_blank");
  });

  $("save-settings").addEventListener("click", saveSettings);
  $("test-mic").addEventListener("click", testMic);
  $("test-voice").addEventListener("click", async () => {
    await api("/api/test_voice", { method: "POST", body: JSON.stringify({ text: "Hi, I'm Helpie. This is how I sound." }) });
  });
  $("notes-clear").addEventListener("click", async () => {
    await api("/api/notes/clear", { method: "POST", body: "{}" });
    loadNotes();
  });
  $("reminders-clear").addEventListener("click", async () => {
    await api("/api/reminders/clear", { method: "POST", body: "{}" });
    renderReminders([]);
  });
  $("memory-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const field = $("memory-text");
    const text = field.value.trim();
    if (!text) return;
    try {
      await api("/api/memory", { method: "POST", body: JSON.stringify({ text }) });
      field.value = "";
    } catch (error) {
      toast("Could not save that.");
    }
  });
  $("memory-clear").addEventListener("click", async () => {
    await api("/api/memory/clear", { method: "POST", body: "{}" });
    renderMemory([]);
  });
  $("update-check").addEventListener("click", () => checkUpdates(true));
  $("update-install").addEventListener("click", installUpdate);
  $("quit-btn").addEventListener("click", () => api("/api/quit", { method: "POST", body: "{}" }));

  $("get-key").addEventListener("click", (event) => {
    event.preventDefault();
    window.open("https://aistudio.google.com/app/apikey", "_blank");
  });
  $("get-porcupine").addEventListener("click", (event) => {
    event.preventDefault();
    window.open("https://console.picovoice.ai/", "_blank");
  });
  $("mic-settings").addEventListener("click", (event) => {
    event.preventDefault();
    window.open("ms-settings:privacy-microphone", "_blank");
  });

  // Tiny view handlers
  $("tiny-close").addEventListener("click", () => {
    setView("chat");
  });
  $("tiny-open-main").addEventListener("click", () => {
    setView("chat");
  });
  $("tiny-mute").addEventListener("click", async () => {
    try {
      await api("/api/stop", { method: "POST", body: "{}" });
      $("tiny-status-text").textContent = "Muted";
      $("tiny-dot").style.background = "var(--red)";
    } catch (error) {
      toast("Could not mute.");
    }
  });

  // Routines + command palette
  initRoutineForm();
  $("palette-input").addEventListener("input", () => {
    paletteIndex = 0;
    paletteRender();
  });
  $("palette-input").addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (paletteShown.length) paletteIndex = (paletteIndex + 1) % paletteShown.length;
      paletteRender();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (paletteShown.length) paletteIndex = (paletteIndex - 1 + paletteShown.length) % paletteShown.length;
      paletteRender();
    } else if (event.key === "Enter") {
      event.preventDefault();
      paletteRun(paletteShown[paletteIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      paletteClose();
    }
  });
  $("palette").addEventListener("mousedown", (event) => {
    if (event.target === $("palette")) paletteClose();
  });

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.code === "Space") {
      event.preventDefault();
      if ($("palette").hidden) paletteOpen();
      else paletteClose();
      return;
    }
    if (event.key === "Escape" && !$("palette").hidden) {
      paletteClose();
      return;
    }
    if (event.ctrlKey && event.key.toLowerCase() === "h") {
      event.preventDefault();
      startListening();
      return;
    }
    if (event.ctrlKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (state.view !== "settings") setView("settings");
      $("settings-search").focus();
      return;
    }
    if (event.key === "Escape" && state.view === "settings") {
      const search = $("settings-search");
      if (document.activeElement === search && search.value) {
        search.value = "";
        refreshNav();
        return;
      }
      setView("chat");
    }
  });
}

/* ------------------------------------------------------------------ */
/*  Boot                                                               */
/* ------------------------------------------------------------------ */
async function boot() {
  bind();
  renderCommands();
  try {
    const data = await api("/api/init");
    state.settings = data.settings;
    state.mics = data.mics || [];
    state.voices = data.voices || [];
    state.languages = data.languages || [];
    state.chats = data.chats || [];
    state.currentChat = data.current_chat || null;
    state.reminders = data.reminders || [];
    state.memory = data.memory || [];
    state.lastEvent = data.last_event || 0;
    $("version").textContent = "v" + data.version;
    $("settings-version").textContent = "v" + data.version;
    $("about-version").textContent = "v" + data.version;
    applySettings();
    setStatus(data.state || "idle");
    renderRecent(state.chats);
    renderReminders(state.reminders);
    renderMemory(state.memory);
    if (data.chat && data.chat.messages && data.chat.messages.length) {
      showChat(data.chat);
    }
    const requested = new URLSearchParams(location.search).get("view");
    if (requested && document.getElementById("view-" + requested)) {
      setView(requested);
    }
    const requestedPage = new URLSearchParams(location.search).get("page");
    if (requestedPage) setSettingsPage(requestedPage);
  } catch (error) {
    toast("Could not connect to Helpie's local server.");
  }
  poll();
}

window.addEventListener("load", () => {
  boot();
});
