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
  ["Notes", '"Take a note: buy milk", "Read my notes"'],
  ["Reminders", '"Remind me in 10 minutes to stretch"'],
  ["System", '"Screenshot", "Lock the screen", "Battery status"'],
  ["Math", '"Calculate 12 times 8", "What is 15 percent of 240"'],
  ["Time", '"What time is it", "What is the date"'],
  ["Turkish works too", '"Chrome\'u aç", "Sesi kıs", "Ekran görüntüsü al"'],
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
  return String(text).replace(/[&<>"']/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]
  ));
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
    commands: ["Commands", "Examples you can say or type"],
    settings: ["Settings", "Voice, microphone and AI configuration"],
  };
  $("view-title").textContent = titles[view][0];
  $("view-sub").textContent = titles[view][1];
  if (view === "notes") loadNotes();
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
      : `<div class="empty">No notes yet. Say “take a note: …” and it will show up here.</div>`;
  } catch (error) {
    toast("Could not load notes.");
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
  addMessage("user", text);
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

  $("key-state").textContent = s.has_key ? "connected (" + s.key_hint + ")" : "not set";
  $("model-chip").className = "chip " + (s.has_key ? "on" : "off");
  $("model-chip").innerHTML = `<span class="dot"></span> AI: ${s.has_key ? "Gemini connected" : "commands only"}`;
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
  };
  const key = $("set-key").value.trim();
  if (key) patch.api_key = key;
  try {
    const data = await api("/api/settings", { method: "POST", body: JSON.stringify(patch) });
    state.settings = data.settings;
    $("set-key").value = "";
    applySettings();
    toast("Settings saved.");
  } catch (error) {
    toast("Could not save settings.");
  }
}

/* ------------------------------------------------------------------ */
/*  Updates                                                            */
/* ------------------------------------------------------------------ */
async function checkUpdates(manual = true) {
  if (manual) toast("Checking for updates…");
  try {
    const result = await api("/api/update/check");
    if (result.error) {
      if (manual) toast(result.error);
      return;
    }
    if (result.available && result.url) {
      state.update = result;
      $("update-banner-text").textContent = `Helpie ${result.latest} is available (you have ${result.current}).`;
      $("update-banner").hidden = false;
      if (manual) toast("Update available: v" + result.latest);
    } else if (manual) {
      toast("You are on the latest version (" + result.current + ").");
    }
  } catch (error) {
    if (manual) toast("Could not check for updates.");
  }
}

async function installUpdate() {
  if (!state.update || !state.update.url) return;
  $("update-install").disabled = true;
  $("update-install").textContent = "Installing…";
  try {
    const result = await api("/api/update/apply", {
      method: "POST",
      body: JSON.stringify({ url: state.update.url }),
    });
    toast(result.message || (result.ok ? "Updated. Restarting…" : "Update failed."));
  } catch (error) {
    toast("Update failed.");
    $("update-install").disabled = false;
    $("update-install").textContent = "Install";
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
      break;
    case "heard":
      addMessage("user", event.text);
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
  $("new-chat").addEventListener("click", () => {
    $("messages").innerHTML = "";
    setView("chat");
    $("input").focus();
    api("/api/new_chat", { method: "POST", body: "{}" }).catch(() => {});
  });

  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => setView(item.dataset.view));
  });

  $("save-settings").addEventListener("click", saveSettings);
  $("test-voice").addEventListener("click", async () => {
    await api("/api/test_voice", { method: "POST", body: JSON.stringify({ text: "Hi, I'm Helpie. This is how I sound." }) });
  });
  $("notes-clear").addEventListener("click", async () => {
    await api("/api/notes/clear", { method: "POST", body: "{}" });
    loadNotes();
  });
  $("update-check").addEventListener("click", () => checkUpdates(true));
  $("update-install").addEventListener("click", installUpdate);
  $("quit-btn").addEventListener("click", () => api("/api/quit", { method: "POST", body: "{}" }));

  $("get-key").addEventListener("click", (event) => {
    event.preventDefault();
    window.open("https://aistudio.google.com/app/apikey", "_blank");
  });
  $("mic-settings").addEventListener("click", (event) => {
    event.preventDefault();
    window.open("ms-settings:privacy-microphone", "_blank");
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
    $("version").textContent = "v" + data.version;
    applySettings();
    setStatus(data.state || "idle");
  } catch (error) {
    toast("Could not connect to Helpie's local server.");
  }
  poll();
}

boot();
