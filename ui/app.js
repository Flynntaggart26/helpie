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
  memory: [],
  micTesting: false,
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
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
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
  const titles = {
    chat: ["Chat", "Press Ctrl + H to speak"],
    notes: ["Notes", "Everything you asked Helpie to remember"],
    reminders: ["Reminders", "Timers that survive a restart"],
    commands: ["Commands", "Examples you can say or type"],
    settings: ["Settings", "Voice, microphone and AI configuration"],
    tiny: ["Helpie", "Listening…"],
  };
  $("view-title").textContent = titles[view][0];
  $("view-sub").textContent = titles[view][1];
  if (view === "notes") {
    loadNotes();
    loadMemory();
  }
  if (view === "reminders") loadReminders();
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
  $("set-rate").value = s.rate || "+0%";
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
  const pk = s.wake_word_access_key || "";
  $("porcupine-key-state").textContent = pk ? "connected (" + pk.slice(-4).padStart(4, "•") + ")" : "not set";
  $("porcupine-key-state").className = pk ? "has-key" : "";

  // AI Providers
  $("set-key").value = "";
  $("key-state").textContent = s.has_key ? "connected (" + s.key_hint + ")" : "not set";
  $("model-chip").className = "chip " + (s.has_key ? "on" : "off");
  $("model-chip").innerHTML = `<span class="dot"></span> AI: ${s.has_key ? "Gemini connected" : "commands only"}`;

  // Ollama settings
  $("set-ollama-url").value = s.ollama_url || "http://localhost:11434";
  $("set-ollama-model").value = s.ollama_model || "llama3.2";

  // OpenAI-compatible settings
  $("set-openai-url").value = s.openai_url || "";
  $("set-openai-key").value = "";
  $("set-openai-model").value = s.openai_model || "";

  // Plugins
  renderPlugins();
}

async function saveSettings() {
  const mic = $("set-mic").value;
  const patch = {
    user_name: $("set-name").value.trim(),
    city: $("set-city").value.trim(),
    rate: $("set-rate").value,
    voice: $("set-voice").value,
    language: $("set-language").value,
    mic_index: mic === "" ? null : Number(mic),
    auto_listen: $("set-autolisten").checked,
    continuous: $("set-continuous").checked,
    check_updates: $("set-updates").checked,
    background_apps: $("set-background").checked,
    wake_word: $("set-wake-word").checked,
    wake_word_access_key: $("set-porcupine-key").value.trim() || undefined,
    autostart: $("set-autostart").checked,
    // Voice
    voice: $("set-voice").value,
    language: $("set-language").value,
    rate: $("set-rate").value,
    // Wake word
    wake_word_access_key: $("set-porcupine-key").value.trim() || undefined,
    // AI Providers
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
    const plugins = data.plugins || [];
    if (!plugins.length) {
      container.innerHTML = `<div class="muted">No plugins found.</div>`;
      return;
    }
    container.innerHTML = plugins.map((p) => `
      <div class="plugin-card">
        <div class="plugin-header">
          <div>
            <strong>${escapeHtml(p.display_name || p.name)}</strong>
            <span class="plugin-version">v${escapeHtml(p.version)}</span>
          </div>
          <label class="check">
            <input type="checkbox" ${p.enabled ? "checked" : ""} data-plugin="${escapeHtml(p.name)}" />
            Enabled
          </label>
        </div>
        <p class="plugin-desc muted">${escapeHtml(p.description)}</p>
        <div class="plugin-commands">
          <strong>Commands:</strong>
          <span class="muted">${p.commands.map(escapeHtml).join(", ")}</span>
        </div>
        ${p.error ? `<div class="plugin-error muted">${escapeHtml(p.error)}</div>` : ""}
        <div class="plugin-actions">
          <button class="ghost" data-action="configure" data-plugin="${escapeHtml(p.name)}" ${!p.enabled ? "disabled" : ""}>Configure</button>
          <button class="ghost" data-action="${p.enabled ? "disable" : "enable"}" data-plugin="${escapeHtml(p.name)}">${p.enabled ? "Disable" : "Enable"}</button>
        </div>
      </div>
    `).join("");

    container.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const action = btn.dataset.action;
        const name = btn.dataset.plugin;
        try {
          if (action === "enable" || action === "disable") {
            await api("/api/plugins/" + action, { method: "POST", body: JSON.stringify({ name }) });
          }
          renderPlugins();
        } catch (error) {
          toast("Could not " + action + " plugin.");
        }
      });
    });
  } catch (error) {
    container.innerHTML = `<div class="muted">Could not load plugins.</div>`;
  }
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

async function poll() {
  try {
    const data = await api("/api/events?after=" + state.lastEvent);
    (data.events || []).forEach((event) => {
      state.lastEvent = Math.max(state.lastEvent, event.id);
      handleEvent(event);
    });
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
}

/* ------------------------------------------------------------------ */
/*  Wiring                                                             */
/* ------------------------------------------------------------------ */
function bind() {
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

  document.addEventListener("keydown", (event) => {
    if (event.ctrlKey && event.key.toLowerCase() === "h") {
      event.preventDefault();
      startListening();
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
    applySettings();
    setStatus(data.state || "idle");
    renderRecent(state.chats);
    renderReminders(state.reminders);
    renderMemory(state.memory);
    if (data.chat && data.chat.messages && data.chat.messages.length) {
      showChat(data.chat);
    }
    const requested = new URLSearchParams(location.search).get("view");
    if (requested && document.getElementById("view-" + requested)) setView(requested);
  } catch (error) {
    toast("Could not connect to Helpie's local server.");
  }
  poll();
}

boot();