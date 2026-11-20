const $ = (id) => document.getElementById(id);

const state = {
  settings: {},
  screenRegionSelection: null,
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
  visualNotes: [],
  activeVisualNoteId: "",
  visualNoteStrokes: [],
  visualNoteItems: [],
  visualNotePointCount: 0,
  visualNoteUndoStack: [],
  activeVisualStroke: null,
  visualNoteDirty: false,
};

const SETTINGS_PAGES = {
  general: ["General"],
  voice: ["Voice"],
  wakeword: ["Wake Word"],
  "provider-active": ["AI Providers", "Active provider"],
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
  ai: ["provider-active", "provider-gemini", "provider-ollama", "provider-custom"],
  plugins: ["plugins"],
};

const STATUS = {
  idle: "ready",
  listening: "listening",
  hearing: "hearing you",
  capturing: "capturing screen",
  thinking: "thinking",
  speaking: "speaking",
};

const COMMANDS = [
  ["Open apps", '"Open Chrome", "Launch Spotify", "Close Notepad"'],
  ["Volume", '"Volume to 40", "Mute", "Turn the volume up"'],
  ["Brightness", '"Brightness 60", "Dim the screen"'],
  ["Wake word", '"Jarvis" / "Computer" - starts listening without Ctrl+H (needs Porcupine AccessKey)'],
  ["Search", '"Search the web for Mars", "YouTube lo-fi beats"'],
  ["Screen", '"What is on my screen", "Explain this error", "Ekranda ne var"'],
  ["Documents", '"Summarize my thesis", "Report dosyasını özetle"'],
  ["Memory", '"Remember that I prefer short answers", "What do you remember about me"'],
  ["Briefing", '"Good morning", "Give me a briefing"'],
  ["One action at a time", 'Multi-step chat actions are unavailable until each action can be reviewed.'],
  ["Organize files", '"Organize downloads by type", "Organize desktop by date" (preview only), "Find duplicates in downloads"'],
  ["Routines", '"Run start_work routine", "Save routine my_morning", "Run routine with params", "List routines"'],
  ["Email & Calendar", '"Read emails", "Show calendar"; sending or creating events is unavailable until separately reviewed.'],
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
    const map = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
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
    chat: ["Chat", "Hold Ctrl + H to speak, release to send"],
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
    loadVisualNotes();
    loadMemory();
    requestAnimationFrame(resizeVisualNoteCanvas);
  }
  if (view === "reminders") loadReminders();
  if (view === "commands") loadRecycleHistory();
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

function formatReviewPath(value) {
  // Make invisible direction controls and line breaks explicit in file reviews.
  return String(value ?? "").replace(/[\u0000-\u001f\u007f-\u009f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]/g,
    char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}

async function inspectWindowControls(token) {
  const status = $("window-inspect-status"), list = $("window-inspect-results");
  list.replaceChildren();
  status.textContent = "Inspecting button names locally…";
  try {
    const data = await api("/api/windows/inspect", { method: "POST", body: JSON.stringify({ token }) });
    for (const control of data.controls || []) {
      const item = document.createElement("li");
      item.textContent = `${formatReviewPath(control.name)} (${control.type})`;
      item.dir = "ltr";
      list.appendChild(item);
    }
    status.textContent = `${(data.controls || []).length} button(s) found (up to 40; some controls may be omitted). This is read-only; nothing was clicked.`;
  } catch (_) {
    status.textContent = "Could not inspect this window. List windows again and retry.";
  }
}

async function loadRecycleHistory() {
  const list = $("recycle-history-items"), status = $("recycle-history-status");
  try {
    const result = await api("/api/recycle/history");
    list.replaceChildren();
    for (const name of result.items || []) {
      const row = document.createElement("li");
      row.textContent = formatReviewPath(name);
      row.dir = "ltr";
      list.appendChild(row);
    }
    status.textContent = result.available
      ? (result.items.length ? `${result.items.length} item(s) moved this session.` : "No items moved by Helpie in this session.")
      : "Recycle Bin moves are not available yet. No Helpie moves can be listed.";
  } catch (_) {
    list.replaceChildren();
    status.textContent = "Could not load Recycle Bin activity.";
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

const VISUAL_NOTE_COLORS = new Set(["#55d6ff", "#f59e0b", "#f472b6", "#f8fafc"]);
let visualPointEditorObject = null;
let activeGeometryDrag = null;

function drawVisualNoteCanvas(showHandles = true) {
  const canvas = $("visual-note-canvas");
  if (!canvas) return;
  refreshVisualPointOptions();
  const description = $("visual-note-description");
  if (description) {
    const text = HelpieNoteSvg.describe(state.visualNoteItems, state.visualNoteStrokes);
    if (description.textContent !== text) description.textContent = text;
  }
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const context = canvas.getContext("2d");
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, rect.width, rect.height);
  drawVisualNoteItems(context, rect.width, rect.height);
  for (const stroke of state.visualNoteStrokes) {
    const points = stroke.points || [];
    if (!points.length || !VISUAL_NOTE_COLORS.has(stroke.color)) continue;
    context.strokeStyle = stroke.color;
    context.fillStyle = stroke.color;
    context.lineWidth = Math.max(1, Math.min(20, Number(stroke.size) || 4));
    context.lineCap = "round";
    context.lineJoin = "round";
    if (points.length === 1) {
      context.beginPath();
      context.arc(points[0].x * rect.width, points[0].y * rect.height,
        context.lineWidth / 2, 0, Math.PI * 2);
      context.fill();
      continue;
    }
    context.beginPath();
    context.moveTo(points[0].x * rect.width, points[0].y * rect.height);
    for (const point of points.slice(1)) {
      context.lineTo(point.x * rect.width, point.y * rect.height);
    }
    context.stroke();
  }
  if (showHandles && $("visual-note-tool")?.value === "geometry") {
    const selected = $("visual-point-select").value;
    context.save();
    for (const handle of HelpieGeometry.handles(state.visualNoteItems)) {
      const point = HelpieGeometry.canvasPosition(state.visualNoteItems, handle.key, rect.width, rect.height);
      if (!point) continue;
      context.beginPath();
      context.arc(point.x, point.y, 6, 0, Math.PI * 2);
      context.fillStyle = handle.key === selected ? "#fbbf24" : "#f8fafc";
      context.strokeStyle = "#075985";
      context.lineWidth = 2;
      context.fill();
      context.stroke();
    }
    context.restore();
  }
}

function refreshVisualPointOptions() {
  const select = $("visual-point-select");
  if (!select) return;
  const choices = HelpieGeometry.handles(state.visualNoteItems);
  const previous = select.value;
  select.replaceChildren();
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = choices.length ? "Choose a handle" : "No geometry handles";
  select.appendChild(empty);
  choices.forEach((choice) => {
    const option = document.createElement("option");
    option.value = choice.key;
    option.textContent = choice.label;
    select.appendChild(option);
  });
  if (choices.some((choice) => choice.key === previous)) select.value = previous;
  const selected = selectedVisualPoint();
  if ((selected?.object || null) !== visualPointEditorObject) loadVisualPointEditor();
}

function selectedVisualPoint() {
  return HelpieGeometry.resolve(state.visualNoteItems, $("visual-point-select").value);
}

function loadVisualPointEditor() {
  const point = selectedVisualPoint();
  visualPointEditorObject = point?.object || null;
  $("visual-point-x").value = point ? String(Math.round(point.x * 10000) / 100) : "";
  $("visual-point-y").value = point ? String(Math.round(point.y * 10000) / 100) : "";
  $("visual-point-x").disabled = point?.part === "radius";
  $("visual-point-y").disabled = point?.part === "radius";
  $("visual-point-label").value = point?.object.label || "";
  const radius = $("visual-point-radius");
  radius.disabled = point?.object.kind !== "circle";
  radius.value = radius.disabled ? "" : String(Math.round(point.object.radius * 10000) / 100);
}

function drawVisualNoteItems(context, width, height) {
  const px = (value) => value * width;
  const py = (value) => value * height;
  const label = (text, x, y, size = 14) => {
    if (typeof text !== "string" || !text.trim()) return;
    context.font = `600 ${size}px Segoe UI, sans-serif`;
    context.lineWidth = 4;
    context.strokeStyle = "#08111d";
    context.fillStyle = "#ffffff";
    context.lineJoin = "round";
    context.strokeText(text.slice(0, 60), x, y);
    context.fillText(text.slice(0, 60), x, y);
  };
  context.save();
  context.lineWidth = 3;
  context.strokeStyle = "#55d6ff";
  context.fillStyle = "#ffca52";
  context.lineCap = "round";
  context.lineJoin = "round";
  for (const item of state.visualNoteItems.slice(0, 3)) {
    if (!item || typeof item !== "object") continue;
    if (item.kind === "pin" && Number.isFinite(item.x) && Number.isFinite(item.y)) {
      context.beginPath(); context.arc(px(item.x), py(item.y), 9, 0, Math.PI * 2); context.fill();
      label(item.label, px(item.x) + 13, py(item.y) - 9);
    } else if (item.kind === "callout" && Number.isFinite(item.x) && Number.isFinite(item.y)
      && Number.isInteger(item.number) && item.number >= 1 && item.number <= 3) {
      context.beginPath(); context.arc(px(item.x), py(item.y), 11, 0, Math.PI * 2); context.fill();
      context.fillStyle = "#07111f"; context.font = "700 13px Segoe UI, sans-serif";
      context.textAlign = "center"; context.textBaseline = "middle";
      context.fillText(String(item.number), px(item.x), py(item.y));
      context.textAlign = "left"; context.textBaseline = "alphabetic"; context.fillStyle = "#ffca52";
      label(item.label, px(item.x) + 15, py(item.y) - 12);
    } else if (item.kind === "rect" && [item.x, item.y, item.width, item.height].every(Number.isFinite)) {
      context.fillStyle = "rgba(255, 202, 82, 0.12)";
      context.fillRect(px(item.x), py(item.y), px(item.width), py(item.height));
      context.strokeRect(px(item.x), py(item.y), px(item.width), py(item.height));
      context.fillStyle = "#ffca52"; label(item.label, px(item.x), py(item.y) - 7);
    } else if ((item.kind === "arrow" || item.kind === "underline") && [item.x1, item.y1, item.x2, item.y2].every(Number.isFinite)) {
      const x1 = px(item.x1), y1 = py(item.y1), x2 = px(item.x2), y2 = py(item.y2);
      const angle = Math.atan2(y2 - y1, x2 - x1);
      context.strokeStyle = "#55d6ff"; context.beginPath(); context.moveTo(x1, y1); context.lineTo(x2, y2); context.stroke();
      if (item.kind === "arrow") { context.beginPath(); context.moveTo(x2, y2);
      context.lineTo(x2 - 11 * Math.cos(angle - 0.45), y2 - 11 * Math.sin(angle - 0.45));
      context.lineTo(x2 - 11 * Math.cos(angle + 0.45), y2 - 11 * Math.sin(angle + 0.45));
      context.closePath(); context.fillStyle = "#55d6ff"; context.fill(); }
      label(item.label, (x1 + x2) / 2, (y1 + y2) / 2 - 8);
    } else if (item.kind === "equation" && typeof item.text === "string") {
      label(item.text.slice(0, 120), px(item.x), py(item.y), 20);
    } else if (item.kind === "graph" && Array.isArray(item.segments)) {
      const gx = px(item.x), gy = py(item.y), gw = px(item.width), gh = py(item.height);
      context.fillStyle = "rgba(8, 17, 29, 0.84)"; context.fillRect(gx, gy, gw, gh);
      context.strokeStyle = "#8299b4"; context.strokeRect(gx, gy, gw, gh);
      context.strokeStyle = "rgba(176, 205, 235, 0.3)"; context.lineWidth = 1;
      for (let tick = 1; tick < 4; tick += 1) {
        context.beginPath(); context.moveTo(gx + gw * tick / 4, gy); context.lineTo(gx + gw * tick / 4, gy + gh); context.stroke();
        context.beginPath(); context.moveTo(gx, gy + gh * tick / 4); context.lineTo(gx + gw, gy + gh * tick / 4); context.stroke();
      }
      context.strokeStyle = "#55d6ff"; context.lineWidth = 2;
      for (const segment of item.segments.slice(0, 65)) {
        if (!Array.isArray(segment) || segment.length < 2 || segment.length > 65
          || !segment.every((point) => Array.isArray(point) && point.length === 2
            && point.every((value) => Number.isFinite(value) && value >= 0 && value <= 1))) continue;
        context.beginPath(); context.moveTo(gx + segment[0][0] * gw, gy + segment[0][1] * gh);
        for (const point of segment.slice(1)) context.lineTo(gx + point[0] * gw, gy + point[1] * gh);
        context.stroke();
      }
      label(`f(x) = ${String(item.expression || "").slice(0, 96)}`, gx, gy - 5);
    } else if (item.kind === "geometry" && Array.isArray(item.objects)) {
      const gx = px(item.x), gy = py(item.y), gw = px(item.width), gh = py(item.height);
      for (const object of item.objects.slice(0, 12)) {
        if (!object || typeof object !== "object") continue;
        context.strokeStyle = "#8be9ff"; context.fillStyle = "#ffca52"; context.lineWidth = 2;
        if (object.kind === "point" && Number.isFinite(object.x) && Number.isFinite(object.y)) {
          const ox = gx + object.x * gw, oy = gy + object.y * gh;
          context.beginPath(); context.arc(ox, oy, 4, 0, Math.PI * 2); context.fill();
          label(object.label, ox + 7, oy - 6, 12);
        } else if (object.kind === "segment" && [object.x1, object.y1, object.x2, object.y2].every(Number.isFinite)) {
          const x1 = gx + object.x1 * gw, y1 = gy + object.y1 * gh;
          const x2 = gx + object.x2 * gw, y2 = gy + object.y2 * gh;
          context.beginPath(); context.moveTo(x1, y1); context.lineTo(x2, y2); context.stroke();
          label(object.label, (x1 + x2) / 2 + 5, (y1 + y2) / 2 - 5, 12);
        } else if (object.kind === "circle" && Number.isFinite(object.radius)) {
          const cx = gx + object.cx * gw, cy = gy + object.cy * gh;
          context.beginPath(); context.ellipse(cx, cy, object.radius * gw, object.radius * gh, 0, 0, Math.PI * 2); context.stroke();
          label(object.label, cx + object.radius * gw + 4, cy, 12);
        } else if (object.kind === "polygon" && Array.isArray(object.points) && object.points.length >= 3 && object.points.length <= 8) {
          context.beginPath(); context.moveTo(gx + object.points[0][0] * gw, gy + object.points[0][1] * gh);
          let centerX = object.points[0][0] / object.points.length;
          let centerY = object.points[0][1] / object.points.length;
          for (const point of object.points.slice(1)) {
            context.lineTo(gx + point[0] * gw, gy + point[1] * gh);
            centerX += point[0] / object.points.length;
            centerY += point[1] / object.points.length;
          }
          context.closePath(); context.stroke();
          label(object.label, gx + centerX * gw + 5, gy + centerY * gh - 5, 12);
        }
      }
      const marks = { horizontal: "↔", vertical: "↕", equal: "=", perpendicular: "⊥", parallel: "∥" };
      for (const constraint of (Array.isArray(item.constraints) ? item.constraints : []).slice(0, 8)) {
        if (!constraint || !Object.prototype.hasOwnProperty.call(marks, constraint.kind)
          || !Array.isArray(constraint.objects)
          || constraint.objects.length !== (constraint.kind === "horizontal"
            || constraint.kind === "vertical" ? 1 : 2)
          || !constraint.objects.every((index) => Number.isInteger(index)
            && index >= 0 && index < item.objects.length
            && item.objects[index]?.kind === "segment")) continue;
        const linked = constraint.objects.map((index) => {
          const segment = item.objects[index];
          return {
            x: gx + (segment.x1 + segment.x2) * gw / 2,
            y: gy + (segment.y1 + segment.y2) * gh / 2,
          };
        });
        label(marks[constraint.kind], linked.reduce((sum, point) => sum + point.x, 0) / linked.length,
          linked.reduce((sum, point) => sum + point.y, 0) / linked.length, 16);
      }
    }
  }
  context.restore();
}

function resizeVisualNoteCanvas() {
  const canvas = $("visual-note-canvas");
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  const width = Math.round(rect.width * ratio);
  const height = Math.round(rect.height * ratio);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  drawVisualNoteCanvas();
}

function renderVisualNotes() {
  const list = $("visual-note-list");
  if (!list) return;
  if (!state.visualNotes.length) {
    list.innerHTML = `<div class="empty">No visual notes saved yet.</div>`;
    return;
  }
  list.innerHTML = state.visualNotes.map((note) => (
    `<div class="visual-note-item">` +
    `<div class="visual-note-item-copy"><strong>${escapeHtml(note.title || "Untitled")}</strong>` +
    `<span>${escapeHtml(note.updated_at || "")} · ${Number(note.stroke_count) || 0} strokes · ${Number(note.visual_count) || 0} visual items</span></div>` +
    `<button class="ghost" type="button" data-visual-note-open="${escapeHtml(note.id)}">Open</button>` +
    `<button class="ghost" type="button" data-visual-note-delete="${escapeHtml(note.id)}" aria-label="Delete ${escapeHtml(note.title || "visual note")}">Delete</button>` +
    `</div>`
  )).join("");
}

async function loadVisualNotes() {
  try {
    const data = await api("/api/visual-notes");
    state.visualNotes = Array.isArray(data.notes) ? data.notes : [];
    renderVisualNotes();
  } catch (error) {
    $("visual-note-list").innerHTML = `<div class="empty">Could not load visual notes.</div>`;
  }
}

function newVisualNote() {
  if (state.visualNoteDirty && !window.confirm("Discard unsaved visual note changes?")) return;
  state.activeVisualNoteId = "";
  state.visualNoteStrokes = [];
  state.visualNoteItems = [];
  state.visualNoteUndoStack = [];
  state.visualNotePointCount = 0;
  state.visualNoteDirty = false;
  $("visual-note-title").value = "";
  $("visual-note-status").textContent = "New note. Draw a sketch, then save it.";
  drawVisualNoteCanvas();
  $("visual-note-title").focus();
}

async function openVisualNote(noteId) {
  if (state.visualNoteDirty && !window.confirm("Discard unsaved visual note changes?")) return;
  try {
    const data = await api("/api/visual-notes/" + encodeURIComponent(noteId));
    const note = data.note;
    state.activeVisualNoteId = note.id;
    state.visualNoteStrokes = Array.isArray(note.strokes) ? note.strokes : [];
    state.visualNoteItems = Array.isArray(note.visual_items) ? note.visual_items : [];
    state.visualNoteUndoStack = [];
    state.visualNotePointCount = state.visualNoteStrokes.reduce(
      (total, stroke) => total + (Array.isArray(stroke.points) ? stroke.points.length : 0), 0);
    state.visualNoteDirty = false;
    $("visual-note-title").value = note.title || "";
    $("visual-note-status").textContent = "Editing saved visual note.";
    drawVisualNoteCanvas();
  } catch (error) {
    toast("Could not open that visual note.");
  }
}

async function saveVisualNote() {
  const title = $("visual-note-title").value.trim();
  if (!title) {
    $("visual-note-status").textContent = "Add a title before saving.";
    $("visual-note-title").focus();
    return;
  }
  try {
    const data = await api("/api/visual-notes/save", {
      method: "POST",
      body: JSON.stringify({
        id: state.activeVisualNoteId,
        title,
        strokes: state.visualNoteStrokes,
        visual_items: state.visualNoteItems,
      }),
    });
    state.activeVisualNoteId = data.note.id;
    state.visualNoteItems = Array.isArray(data.note.visual_items)
      ? data.note.visual_items : state.visualNoteItems;
    state.visualNoteDirty = false;
    $("visual-note-status").textContent = "Visual note saved on this device.";
    await loadVisualNotes();
  } catch (error) {
    $("visual-note-status").textContent = "Could not save. Check the title and drawing size.";
  }
}

function pushVisualNoteUndo() {
  state.visualNoteUndoStack.push({
    strokes: JSON.parse(JSON.stringify(state.visualNoteStrokes)),
    visualItems: JSON.parse(JSON.stringify(state.visualNoteItems)),
  });
  if (state.visualNoteUndoStack.length > 20) state.visualNoteUndoStack.shift();
}

function undoVisualNote() {
  const previous = state.visualNoteUndoStack.pop();
  if (!previous) return;
  state.visualNoteStrokes = previous.strokes;
  state.visualNoteItems = previous.visualItems;
  state.visualNotePointCount = state.visualNoteStrokes.reduce(
    (total, stroke) => total + (stroke.points?.length || 0), 0);
  state.visualNoteDirty = true;
  state.activeVisualStroke = null;
  $("visual-note-status").textContent = "Last change undone. Save to keep this change.";
  drawVisualNoteCanvas();
}

function beginGeometryDrag(event) {
  if (activeGeometryDrag || (event.pointerType === "mouse" && event.button !== 0)) return;
  const canvas = $("visual-note-canvas");
  const rect = canvas.getBoundingClientRect();
  const key = HelpieGeometry.hitTest(state.visualNoteItems, rect.width, rect.height,
    event.clientX - rect.left, event.clientY - rect.top);
  const target = key && HelpieGeometry.resolve(state.visualNoteItems, key);
  if (!target) {
    $("visual-note-status").textContent = "Drag a visible handle to move it.";
    return;
  }
  $("visual-point-select").value = key;
  loadVisualPointEditor();
  activeGeometryDrag = {
    key, pointerId: event.pointerId, item: state.visualNoteItems[target.i],
    i: target.i, j: target.j, original: JSON.parse(JSON.stringify(target.object)),
    before: { strokes: JSON.parse(JSON.stringify(state.visualNoteStrokes)),
      visualItems: JSON.parse(JSON.stringify(state.visualNoteItems)) },
    wasDirty: state.visualNoteDirty, changed: false,
  };
  canvas.setPointerCapture(event.pointerId);
  drawVisualNoteCanvas();
}

function continueGeometryDrag(event) {
  const drag = activeGeometryDrag;
  if (!drag || drag.pointerId !== event.pointerId || state.visualNoteItems[drag.i] !== drag.item) return;
  const rect = $("visual-note-canvas").getBoundingClientRect();
  const local = HelpieGeometry.localPosition(state.visualNoteItems, drag.key, rect.width, rect.height,
    event.clientX - rect.left, event.clientY - rect.top);
  if (!local) return;
  const current = HelpieGeometry.resolve(state.visualNoteItems, drag.key);
  if (!current) return;
  const edit = HelpieGeometry.propose(state.visualNoteItems, drag.key,
    Number(local.x.toFixed(4)), Number(local.y.toFixed(4)), current.object.label || "");
  if (!edit) return;
  drag.item.objects[drag.j] = edit.object;
  drag.changed = JSON.stringify(edit.object) !== JSON.stringify(drag.original);
  state.visualNoteDirty = drag.wasDirty || drag.changed;
  drawVisualNoteCanvas();
}

function finishGeometryDrag(event, cancelled = false) {
  const drag = activeGeometryDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  activeGeometryDrag = null;
  if (state.visualNoteItems[drag.i] !== drag.item) return;
  if (cancelled) {
    drag.item.objects[drag.j] = drag.original;
    state.visualNoteDirty = drag.wasDirty;
    $("visual-note-status").textContent = "Geometry move cancelled.";
  } else if (drag.changed) {
    state.visualNoteUndoStack.push(drag.before);
    if (state.visualNoteUndoStack.length > 20) state.visualNoteUndoStack.shift();
    $("visual-note-status").textContent = "Geometry moved. Save the note to keep the change.";
  }
  drawVisualNoteCanvas();
}

async function importLatestVisualAnswer() {
  try {
    const data = await api("/api/visual-notes/current");
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      $("visual-note-status").textContent = "No recent Helpie answer is available to import.";
      return;
    }
    if (state.visualNoteItems.length + items.length > 3) {
      $("visual-note-status").textContent = "This note can contain up to three visual items.";
      return;
    }
    pushVisualNoteUndo();
    state.visualNoteItems.push(...items);
    if (!$("visual-note-title").value.trim()) $("visual-note-title").value = "Helpie visual answer";
    state.visualNoteDirty = true;
    $("visual-note-status").textContent = "Imported the recent vector answer. Save to keep it on this device.";
    drawVisualNoteCanvas();
  } catch (error) {
    $("visual-note-status").textContent = "Could not import the recent Helpie answer.";
  }
}

async function exportVisualNote() {
  const title = $("visual-note-title").value.trim() || "Untitled visual note";
  try {
    await api("/api/visual-notes/exported", { method: "POST", body: "{}" });
  } catch (error) {
    $("visual-note-status").textContent = "Could not prepare the note export.";
    return;
  }
  const payload = {
    format: "helpie-visual-note",
    version: 1,
    title,
    strokes: state.visualNoteStrokes,
    visual_items: state.visualNoteItems,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${title.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 60) || "visual-note"}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  $("visual-note-status").textContent = "Exported this note as a local JSON file.";
}

async function exportVisualNotePng() {
  const canvas = $("visual-note-canvas");
  drawVisualNoteCanvas(false);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
  drawVisualNoteCanvas();
  if (!blob) {
    $("visual-note-status").textContent = "Could not create the PNG image.";
    return;
  }
  try {
    await api("/api/visual-notes/exported", { method: "POST", body: "{}" });
  } catch (error) {
    $("visual-note-status").textContent = "Could not prepare the note export.";
    return;
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const title = $("visual-note-title").value.trim() || "visual-note";
  anchor.download = `${title.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 60) || "visual-note"}.png`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  $("visual-note-status").textContent = "Exported this note as a PNG image.";
}

async function exportVisualNotePdf() {
  const canvas = $("visual-note-canvas");
  try {
    drawVisualNoteCanvas(false);
    const image = await new Promise(resolve => canvas.toBlob(resolve, "image/jpeg", 0.92));
    drawVisualNoteCanvas();
    if (!image || image.type !== "image/jpeg") throw new Error("JPEG unavailable");
    const pdf = HelpieNotePdf.build(new Uint8Array(await image.arrayBuffer()), canvas.width, canvas.height);
    await api("/api/visual-notes/exported", { method: "POST", body: "{}" });
    const url = URL.createObjectURL(pdf);
    const anchor = document.createElement("a");
    const title = $("visual-note-title").value.trim() || "visual-note";
    anchor.href = url;
    anchor.download = `${title.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 60) || "visual-note"}.pdf`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $("visual-note-status").textContent = "Exported this note as an image-based PDF.";
  } catch (error) {
    drawVisualNoteCanvas();
    $("visual-note-status").textContent = "Could not export this note as PDF.";
  }
}

async function exportVisualNoteSvg() {
  try {
    const rect = $("visual-note-canvas").getBoundingClientRect();
    const svg = HelpieNoteSvg.build(state.visualNoteItems, state.visualNoteStrokes,
      Math.round(rect.width), Math.round(rect.height));
    await api("/api/visual-notes/exported", { method: "POST", body: "{}" });
    const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
    const anchor = document.createElement("a");
    const title = $("visual-note-title").value.trim() || "visual-note";
    anchor.href = url;
    anchor.download = `${title.replace(/[^a-z0-9_-]+/gi, "-").slice(0, 60) || "visual-note"}.svg`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $("visual-note-status").textContent = "Exported this note as vector SVG.";
  } catch (error) {
    $("visual-note-status").textContent = "Could not export this note as SVG.";
  }
}

function beginVisualNoteStroke(event) {
  const canvas = $("visual-note-canvas");
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height || state.visualNoteStrokes.length >= 200
    || state.visualNotePointCount >= 10000) {
    $("visual-note-status").textContent = "This note reached its drawing limit. Save it or start a new note.";
    return;
  }
  const color = $("visual-note-color").value;
  if (!VISUAL_NOTE_COLORS.has(color)) return;
  const point = {
    x: Number(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)).toFixed(4)),
    y: Number(Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)).toFixed(4)),
  };
  const stroke = {
    color,
    size: Math.max(1, Math.min(20, Number($("visual-note-size").value) || 4)),
    points: [point],
  };
  pushVisualNoteUndo();
  state.visualNoteStrokes.push(stroke);
  state.visualNotePointCount += 1;
  state.visualNoteDirty = true;
  state.activeVisualStroke = stroke;
  canvas.setPointerCapture(event.pointerId);
  drawVisualNoteCanvas();
}

function continueVisualNoteStroke(event) {
  const stroke = state.activeVisualStroke;
  if (!stroke || stroke.points.length >= 500 || state.visualNotePointCount >= 10000) return;
  const canvas = $("visual-note-canvas");
  const rect = canvas.getBoundingClientRect();
  stroke.points.push({
    x: Number(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)).toFixed(4)),
    y: Number(Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)).toFixed(4)),
  });
  state.visualNotePointCount += 1;
  drawVisualNoteCanvas();
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
        await confirmDataAction("forget_memory", { text: button.dataset.memory });
      } catch (error) {
        toast("Could not forget that.");
      }
    });
  });
}

async function confirmDataAction(action, args) {
  const draft = await api("/api/action-approval/prepare", {
    method: "POST", body: JSON.stringify({ action, args }),
  });
  if (!window.confirm(`${draft.preview}\n\nConfirm this action?`)) {
    await api("/api/action-approval/cancel", { method: "POST", body: JSON.stringify({ token: draft.token }) });
    return false;
  }
  return api("/api/action-approval/confirm", {
    method: "POST", body: JSON.stringify({ token: draft.token }),
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

async function startListening(reason = "chat") {
  try {
    await api("/api/listen", { method: "POST", body: JSON.stringify({ reason }) });
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
  $("set-groq-transcription").checked = !!s.groq_speech_consent;
  $("remove-groq-speech-key").disabled = !s.has_groq_speech_key;
  $("remove-wake-word-key").disabled = !s.has_wake_word_key;
  $("remove-gemini-key").disabled = !s.has_key;
  $("remove-openai-key").disabled = !s.has_openai_key;
  $("set-groq-speech-key").value = "";
  $("groq-speech-key-state").textContent = s.has_groq_speech_key
    ? "A key is saved securely. Leave blank to keep it." : "Enter a Groq key; it is saved securely on this PC.";
  $("set-cloud-tts").checked = !!s.cloud_tts_consent;
  updateVoiceOutputStatus();
  $("set-screen-context").checked = !!s.screen_context_consent;
  $("set-companion-live-view").checked = !!s.companion_live_view_consent;
  $("set-companion-live-view").disabled = !s.screen_context_consent;
  const screenTarget = s.screen_capture_target || "picker";
  $("set-screen-target").value = screenTarget;
  $("screen-region-block").hidden = screenTarget !== "region";
  const selectedRegion = state.screenRegionSelection || s.screen_capture_region;
  $("screen-region-status").textContent = selectedRegion
    ? `Region selected (${Math.round(selectedRegion.width * 100)}% × ${Math.round(selectedRegion.height * 100)}% of the chosen display).`
    : "No region selected. Save screen access and choose a display first.";
  $("set-wake-word").checked = !!s.wake_word;
  const hasWakeWordKey = !!s.has_wake_word_key;
  $("porcupine-key-state").textContent = hasWakeWordKey ? "connected" : "not set";
  $("porcupine-key-state").className = "badge" + (hasWakeWordKey ? " has-key" : "");
  $("set-autolisten").checked = !!s.auto_listen;
  $("set-continuous").checked = !!s.continuous;
  $("set-updates").checked = !!s.check_updates;
  $("set-background").checked = s.background_apps !== false;
  $("set-autostart").checked = !!s.autostart;

  // Voice settings
  $("set-voice").value = s.voice || "";
  $("set-language").value = s.language || "";
  $("set-rate").value = s.rate || "+0%";

  // AI Providers
  $("set-provider").value = s.provider || "gemini";
  $("set-key").value = "";
  $("key-state").textContent = s.has_key ? "connected (" + s.key_hint + ")" : "not set";
  $("key-state").className = "badge" + (s.has_key ? " has-key" : "");
  const chip = providerChip(s);
  $("model-chip").className = "chip " + (chip.on ? "on" : "off");
  $("model-chip").innerHTML = `<span class="dot"></span> AI: ${chip.label}`;

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

function providerChip(s) {
  const provider = s.provider || "gemini";
  if (provider === "ollama") {
    return { on: true, label: "Ollama (local)" };
  }
  if (provider === "openai") {
    const base = (s.openai_url || "").toLowerCase();
    const name = base.includes("openrouter") ? "OpenRouter"
      : base.includes("groq") ? "Groq" : "Custom provider";
    const cloudKeyRequired = base.includes("openrouter.ai") || base.includes("api.groq.com");
    const configured = !!s.openai_url && (!cloudKeyRequired || !!s.has_openai_key);
    return { on: configured, label: configured ? name : "commands only" };
  }
  return { on: !!s.has_key, label: s.has_key ? "Gemini connected" : "commands only" };
}

let voiceSelectionPending = Promise.resolve();
function updateVoiceOutputStatus() {
  $("voice-selection-status").textContent = (state.settings || {}).cloud_tts_consent
    ? "Online voice is on. The selected voice is used for replies and Ctrl+H."
    : "Online voice is off. Replies use the default Windows voice. Turn on the switch above to use your selected voice.";
}
function saveVoiceSelection() {
  const select = $("set-voice"), chosen = select.value;
  const previous = (state.settings || {}).voice;
  select.disabled = true;
  $("voice-selection-status").textContent = "Saving voice…";
  voiceSelectionPending = voiceSelectionPending.then(() => api("/api/voice/select", { method: "POST", body: JSON.stringify({ voice: chosen }) }))
    .then(() => {
      state.settings.voice = chosen;
      updateVoiceOutputStatus();
    })
    .catch(() => {
      select.value = previous || "";
      $("voice-selection-status").textContent = "Could not save voice. Please try again.";
    })
    .finally(() => { select.disabled = false; });
  return voiceSelectionPending;
}

function saveVoiceOutputPreference() {
  const toggle = $("set-cloud-tts"), enabled = toggle.checked;
  toggle.disabled = true;
  $("voice-selection-status").textContent = "Saving online voice setting…";
  voiceSelectionPending = voiceSelectionPending.then(() => api("/api/voice/output", {
    method: "POST", body: JSON.stringify({ cloud_tts_consent: enabled }),
  })).then(() => {
    state.settings.cloud_tts_consent = enabled;
    updateVoiceOutputStatus();
  }).catch(() => {
    toggle.checked = !!(state.settings || {}).cloud_tts_consent;
    $("voice-selection-status").textContent = "Could not save the online voice setting. Please try again.";
  }).finally(() => { toggle.disabled = false; });
  return voiceSelectionPending;
}

async function removeCredential(field, buttonId, inputId) {
  if (!window.confirm("Remove this saved key from Helpie on this PC? You will need to enter it again to use it.")) return;
  const button = $(buttonId);
  button.disabled = true;
  try {
    const result = await api("/api/settings/credentials/remove", {
      method: "POST", body: JSON.stringify({ credential: field }),
    });
    state.settings = result.settings;
    $(inputId).value = "";
    if (field === "groq_speech_key") {
      $("set-groq-transcription").checked = false;
      $("groq-speech-key-state").textContent = "Key removed. Groq transcription is off.";
    } else if (field === "wake_word_access_key") {
      $("set-wake-word").checked = false;
      $("porcupine-key-state").textContent = "not set";
      $("porcupine-key-state").className = "badge";
    } else {
      const badge = $(field === "api_key" ? "key-state" : "openai-key-state");
      badge.textContent = "not set";
      badge.className = "badge";
    }
    toast("Saved key removed.");
  } catch (error) {
    button.disabled = false;
    toast("Could not remove the saved key.");
  }
}

async function saveSettings() {
  await voiceSelectionPending;
  const mic = $("set-mic").value;
  const screenTarget = $("set-screen-target").value;
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
    groq_speech_consent: $("set-groq-transcription").checked,
    groq_speech_key: $("set-groq-speech-key").value.trim() || undefined,
    cloud_tts_consent: $("set-cloud-tts").checked,
    screen_context_consent: $("set-screen-context").checked,
    companion_live_view_consent: $("set-screen-context").checked
      && $("set-companion-live-view").checked,
    screen_capture_target: screenTarget,
    screen_capture_target_id: "",
    screen_capture_region: state.screenRegionSelection || (screenTarget === "region"
      ? (state.settings || {}).screen_capture_region || null : null),
    wake_word: $("set-wake-word").checked,
    wake_word_access_key: $("set-porcupine-key").value.trim() || undefined,
    // AI providers
    provider: $("set-provider").value,
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
    state.screenRegionSelection = null;
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

let screenRegionImage = null;
let screenRegionAnchor = null;
let screenRegionRect = null;

async function openScreenRegionPicker() {
  if (!$("set-screen-context").checked || !state.settings.screen_context_consent) {
    toast("Save screen access in Settings first.");
    return;
  }
  try {
    const preview = await api("/api/screen/preview", {
      method: "POST",
      body: JSON.stringify({}),
    });
    const canvas = $("screen-region-canvas");
    screenRegionImage = new Image();
    screenRegionImage.onload = () => {
      canvas.width = screenRegionImage.naturalWidth;
      canvas.height = screenRegionImage.naturalHeight;
      screenRegionRect = null;
      screenRegionAnchor = null;
      $("screen-region-apply").disabled = true;
      $("screen-region-selection").textContent = "Drag to select an area.";
      drawScreenRegionPreview();
      $("screen-region-modal").hidden = false;
      $("screen-region-cancel").focus();
    };
    screenRegionImage.src = `data:image/jpeg;base64,${preview.image}`;
  } catch (error) {
    toast("Could not show a preview of that selection.");
  }
}

function drawScreenRegionPreview() {
  const canvas = $("screen-region-canvas");
  if (!screenRegionImage || !canvas.width || !canvas.height) return;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(screenRegionImage, 0, 0, canvas.width, canvas.height);
  if (screenRegionRect) {
    context.fillStyle = "rgba(37, 99, 235, 0.24)";
    context.fillRect(screenRegionRect.x, screenRegionRect.y, screenRegionRect.width, screenRegionRect.height);
    context.strokeStyle = "#60a5fa";
    context.lineWidth = Math.max(2, canvas.width / 700);
    context.strokeRect(screenRegionRect.x, screenRegionRect.y, screenRegionRect.width, screenRegionRect.height);
  }
}

function closeScreenRegionPicker() {
  $("screen-region-modal").hidden = true;
  const canvas = $("screen-region-canvas");
  canvas.width = 0;
  canvas.height = 0;
  screenRegionImage = null;
  screenRegionAnchor = null;
  screenRegionRect = null;
}

function screenRegionPoint(event) {
  const canvas = $("screen-region-canvas");
  const bounds = canvas.getBoundingClientRect();
  return {
    x: Math.max(0, Math.min(canvas.width, (event.clientX - bounds.left) * canvas.width / bounds.width)),
    y: Math.max(0, Math.min(canvas.height, (event.clientY - bounds.top) * canvas.height / bounds.height)),
  };
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
      $("update-banner-text").textContent = `Helpie ${data.latest} is available (you have ${data.current}).`;
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
    else toast(result.message || "Update failed.");
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
      if (event.kind === "speech") $("voice-selection-status").textContent = event.text;
      else setStatus("idle");
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
        const result = await confirmDataAction("delete_routine", { name: button.dataset.delete });
        if (result) {
          toast(result.result || "Routine action completed.");
          loadRoutines();
        }
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
  $("recycle-history-refresh").addEventListener("click", loadRecycleHistory);
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
    const value = event.target.value;
    if (SETTINGS_PAGES[value]) {
      state.scope = "all";
      refreshNav();
      setSettingsPage(value);
      return;
    }
    state.scope = value;
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
  $("remove-groq-speech-key").addEventListener("click", () => removeCredential("groq_speech_key", "remove-groq-speech-key", "set-groq-speech-key"));
  $("remove-wake-word-key").addEventListener("click", () => removeCredential("wake_word_access_key", "remove-wake-word-key", "set-porcupine-key"));
  $("remove-gemini-key").addEventListener("click", () => removeCredential("api_key", "remove-gemini-key", "set-key"));
  $("remove-openai-key").addEventListener("click", () => removeCredential("openai_key", "remove-openai-key", "set-openai-key"));
  $("set-screen-context").addEventListener("change", () => {
    const liveView = $("set-companion-live-view");
    liveView.disabled = !$("set-screen-context").checked;
    if (liveView.disabled) liveView.checked = false;
  });
  $("set-screen-target").addEventListener("change", () => {
    $("screen-region-block").hidden = $("set-screen-target").value !== "region";
  });
  $("screen-region-choose").addEventListener("click", openScreenRegionPicker);
  $("screen-region-cancel").addEventListener("click", closeScreenRegionPicker);
  $("screen-region-canvas").addEventListener("pointerdown", (event) => {
    const canvas = $("screen-region-canvas");
    screenRegionAnchor = screenRegionPoint(event);
    screenRegionRect = { x: screenRegionAnchor.x, y: screenRegionAnchor.y, width: 0, height: 0 };
    canvas.setPointerCapture(event.pointerId);
    drawScreenRegionPreview();
  });
  $("screen-region-canvas").addEventListener("pointermove", (event) => {
    if (!screenRegionAnchor) return;
    const point = screenRegionPoint(event);
    screenRegionRect = {
      x: Math.min(screenRegionAnchor.x, point.x),
      y: Math.min(screenRegionAnchor.y, point.y),
      width: Math.abs(point.x - screenRegionAnchor.x),
      height: Math.abs(point.y - screenRegionAnchor.y),
    };
    drawScreenRegionPreview();
  });
  $("screen-region-canvas").addEventListener("pointerup", () => {
    if (!screenRegionRect) return;
    screenRegionAnchor = null;
    const canvas = $("screen-region-canvas");
    const usable = screenRegionRect.width >= 12 && screenRegionRect.height >= 12;
    $("screen-region-apply").disabled = !usable;
    $("screen-region-selection").textContent = usable
      ? `${Math.round(screenRegionRect.width / canvas.width * 100)}% × ${Math.round(screenRegionRect.height / canvas.height * 100)}% selected.`
      : "Select a larger area.";
  });
  $("screen-region-canvas").addEventListener("pointercancel", () => {
    screenRegionAnchor = null;
    screenRegionRect = null;
    $("screen-region-apply").disabled = true;
    drawScreenRegionPreview();
  });
  $("screen-region-apply").addEventListener("click", () => {
    if (!screenRegionRect) return;
    const canvas = $("screen-region-canvas");
    const x = screenRegionRect.x / canvas.width;
    const y = screenRegionRect.y / canvas.height;
    state.screenRegionSelection = {
      x,
      y,
      width: Math.min(1 - x, screenRegionRect.width / canvas.width),
      height: Math.min(1 - y, screenRegionRect.height / canvas.height),
    };
    closeScreenRegionPicker();
    applySettings();
  });
  $("test-mic").addEventListener("click", testMic);
  $("set-voice").addEventListener("change", saveVoiceSelection);
  $("set-cloud-tts").addEventListener("change", saveVoiceOutputPreference);
  $("test-voice").addEventListener("click", async () => {
    await voiceSelectionPending;
    if (!(state.settings || {}).cloud_tts_consent) {
      updateVoiceOutputStatus();
      toast("Turn on Microsoft Edge neural voice to test the selected voice.");
      return;
    }
    await api("/api/test_voice", { method: "POST", body: JSON.stringify({ text: "Hi, I'm Helpie. This is how I sound." }) });
  });
  $("notes-clear").addEventListener("click", async () => {
    toast("Ask Helpie to clear notes in chat, then confirm.");
  });
  $("visual-note-new").addEventListener("click", newVisualNote);
  $("visual-note-save").addEventListener("click", saveVisualNote);
  $("visual-note-import-answer").addEventListener("click", importLatestVisualAnswer);
  $("visual-note-export").addEventListener("click", exportVisualNote);
  $("visual-note-export-png").addEventListener("click", exportVisualNotePng);
  $("visual-note-export-pdf").addEventListener("click", exportVisualNotePdf);
  $("visual-note-export-svg").addEventListener("click", exportVisualNoteSvg);
  $("window-review-start").addEventListener("click", async () => {
    const button = $("window-review-start"), status = $("window-review-status"), list = $("window-review-results");
    button.disabled = true;
    list.replaceChildren();
    status.textContent = "Listing open windows on this PC…";
    try {
      const data = await api("/api/windows/review", { method: "POST", body: "{}" });
      for (const windowInfo of data.windows || []) {
        const item = document.createElement("li");
        const label = document.createElement("span");
        label.textContent = formatReviewPath(windowInfo.title);
        const inspect = document.createElement("button");
        inspect.type = "button";
        inspect.className = "ghost";
        inspect.textContent = "Inspect buttons";
        inspect.setAttribute("aria-label", `Inspect buttons in ${formatReviewPath(windowInfo.title)}`);
        inspect.addEventListener("click", () => inspectWindowControls(windowInfo.token));
        item.append(label, inspect);
        item.dir = "ltr";
        list.appendChild(item);
      }
      $("window-inspect-results").replaceChildren();
      $("window-inspect-status").textContent = "Select a listed window to inspect its buttons.";
      status.textContent = `${(data.windows || []).length} window(s) listed locally.${data.limited ? " More windows were omitted." : ""}`;
    } catch (_) {
      status.textContent = "Could not list open windows.";
    } finally {
      button.disabled = false;
    }
  });
  let reviewRoot = "", reviewToken = null;
  function clearRecheckStatus() {
    $("file-review-results").querySelectorAll(".file-review-result-status").forEach(node => { node.textContent = ""; });
    $("file-review-recheck-status").textContent = "Rechecking is read-only. Results can change again at any time.";
  }
  function updateReviewSelection() {
    const count = $("file-review-results").querySelectorAll('input[type="checkbox"]:checked').length;
    $("file-review-selection").textContent = `${count} item(s) selected for review. Nothing is deleted.`;
    $("file-review-clear").disabled = count === 0;
    $("file-review-recheck").disabled = count === 0;
    $("file-review-prepare").disabled = count === 0;
  }
  function clearReviewResults() {
    $("file-review-results").replaceChildren();
    reviewRoot = "";
    clearRecheckStatus();
    updateReviewSelection();
  }
  $("file-review-clear").addEventListener("click", () => {
    $("file-review-results").querySelectorAll('input[type="checkbox"]:checked').forEach(input => { input.checked = false; });
    clearRecheckStatus();
    updateReviewSelection();
  });
  for (const id of ["file-review-folder", "file-review-kind"]) {
    $(id).addEventListener("change", () => {
      clearReviewResults();
      $("file-review-status").textContent = "Options changed. Review again to see current results.";
    });
  }
  $("file-review-start").addEventListener("click", async () => {
    const button = $("file-review-start"), status = $("file-review-status"), list = $("file-review-results");
    button.disabled = true;
    $("file-review-folder").disabled = true;
    $("file-review-kind").disabled = true;
    clearReviewResults();
    status.textContent = "Reviewing files on this device…";
    try {
      const result = await api("/api/file-review/preview", { method: "POST", body: JSON.stringify({
        folder: $("file-review-folder").value, kind: $("file-review-kind").value,
      }) });
      reviewRoot = result.root;
      for (const item of result.items || []) {
        const row = document.createElement("li");
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.reviewItem = { path: item.path, fingerprint: item.fingerprint };
        checkbox.addEventListener("change", () => { clearRecheckStatus(); updateReviewSelection(); });
        const description = document.createElement("span");
        description.dir = "ltr";
        description.textContent = item.matches ? `${formatReviewPath(item.path)} — matches ${formatReviewPath(item.matches)} (${item.size} bytes)`
          : Number.isFinite(item.size) ? `${formatReviewPath(item.path)} (${item.size} bytes)` : formatReviewPath(item.path);
        label.append(checkbox, description);
        const resultStatus = document.createElement("span");
        resultStatus.className = "file-review-result-status";
        row.append(label, resultStatus);
        list.appendChild(row);
      }
      status.textContent = `${formatReviewPath(result.root)}: ${result.items.length} result(s). Nothing was deleted.${result.limited ? " Review was limited; results may be incomplete." : ""}`;
    } catch (_) {
      status.textContent = "Could not review that folder. Check that it exists and is accessible.";
    } finally {
      button.disabled = false;
      $("file-review-folder").disabled = false;
      $("file-review-kind").disabled = false;
    }
  });
  $("file-review-recheck").addEventListener("click", async () => {
    const selected = [...$("file-review-results").querySelectorAll('input[type="checkbox"]:checked')];
    if (!selected.length) return;
    const controls = [$("file-review-start"), $("file-review-folder"), $("file-review-kind"), $("file-review-clear"), $("file-review-recheck"), $("file-review-prepare"), ...$("file-review-results").querySelectorAll('input[type="checkbox"]')];
    controls.forEach(control => { control.disabled = true; });
    clearRecheckStatus();
    const status = $("file-review-recheck-status");
    status.textContent = "Rechecking selected items on this device…";
    try {
      const result = await api("/api/file-review/recheck", { method: "POST", body: JSON.stringify({
        folder: $("file-review-folder").value, kind: $("file-review-kind").value,
        selected: selected.map(input => input.reviewItem),
      }) });
      const byPath = new Map(result.items.map(item => [item.path, item.unchanged]));
      for (const input of selected) {
        const marker = input.closest("li").querySelector(".file-review-result-status");
        marker.textContent = byPath.get(input.reviewItem.path) === true ? "Still matches previous review" : "Changed or could not be verified";
      }
      const unchanged = result.items.filter(item => item.unchanged).length;
      status.textContent = `${unchanged} of ${selected.length} selected item(s) still match the earlier review. Others changed or could not be verified.${result.limited ? " The scan was limited." : ""} Nothing was deleted; items can change again at any time.`;
    } catch (_) {
      status.textContent = "Could not recheck the selection. Nothing was deleted.";
    } finally {
      controls.forEach(control => { control.disabled = false; });
      updateReviewSelection();
    }
  });
  $("file-review-prepare").addEventListener("click", async () => {
    const selected = [...$("file-review-results").querySelectorAll('input[type="checkbox"]:checked')];
    if (!selected.length) return;
    const controls = [$("file-review-start"), $("file-review-folder"), $("file-review-kind"), $("file-review-clear"), $("file-review-recheck"), $("file-review-prepare"), ...$("file-review-results").querySelectorAll('input[type="checkbox"]')];
    controls.forEach(control => { control.disabled = true; });
    const status = $("file-review-recheck-status");
    status.textContent = "Checking the selection before showing your review…";
    try {
      const result = await api("/api/file-review/prepare-review", { method: "POST", body: JSON.stringify({
        folder: $("file-review-folder").value, kind: $("file-review-kind").value,
        selected: selected.map(input => input.reviewItem),
      }) });
      reviewToken = result.token;
      $("file-review-dialog-root").textContent = `Folder: ${formatReviewPath(reviewRoot)} · ${selected.length} selected item(s)`;
      const list = $("file-review-dialog-items");
      list.replaceChildren();
      for (const input of selected) {
        const row = document.createElement("li");
        row.dir = "ltr";
        row.textContent = input.closest("label").querySelector("span").textContent;
        list.appendChild(row);
      }
      $("file-review-dialog").showModal();
      status.textContent = "Review the selected items. Nothing will be deleted.";
    } catch (_) {
      status.textContent = "Could not prepare this review. Items may have changed or the scan was incomplete. Nothing was deleted.";
    } finally {
      controls.forEach(control => { control.disabled = false; });
      updateReviewSelection();
    }
  });
  $("file-review-dialog-cancel").addEventListener("click", () => $("file-review-dialog").close());
  $("file-review-dialog").addEventListener("close", () => {
    if (reviewToken) {
      reviewToken = null;
      api("/api/file-review/cancel-review", { method: "POST" }).catch(() => {});
      $("file-review-recheck-status").textContent = "Review cancelled. Nothing was deleted.";
    }
  });
  $("file-review-dialog-confirm").addEventListener("click", async () => {
    if (!reviewToken) return;
    const token = reviewToken;
    reviewToken = null;
    const confirmButton = $("file-review-dialog-confirm"), cancelButton = $("file-review-dialog-cancel");
    confirmButton.disabled = cancelButton.disabled = true;
    try {
      await api("/api/file-review/confirm-review", { method: "POST", body: JSON.stringify({ token }) });
      $("file-review-recheck-status").textContent = "Review confirmed. Nothing was deleted or approved for deletion.";
    } catch (_) {
      $("file-review-recheck-status").textContent = "Review expired or the items changed. Review them again. Nothing was deleted.";
    } finally {
      confirmButton.disabled = cancelButton.disabled = false;
      $("file-review-dialog").close();
    }
  });
  $("visual-point-select").addEventListener("change", loadVisualPointEditor);
  $("visual-note-tool").addEventListener("change", () => {
    $("visual-note-status").textContent = $("visual-note-tool").value === "geometry"
      ? "Drag a visible handle, or use the coordinate controls below."
      : "Draw on the canvas.";
    drawVisualNoteCanvas();
  });
  $("visual-point-apply").addEventListener("click", () => {
    const xField = $("visual-point-x"), yField = $("visual-point-y");
    const x = Number(xField.value), y = Number(yField.value);
    const radiusField = $("visual-point-radius");
    const radius = radiusField.disabled ? undefined : Number(radiusField.value) / 100;
    if (!xField.value.trim() || !yField.value.trim()
        || (!radiusField.disabled && !radiusField.value.trim())
        || !Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 100 || y < 0 || y > 100) {
      $("visual-note-status").textContent = "Choose a handle and enter coordinates from 0 to 100.";
      return;
    }
    const edit = HelpieGeometry.propose(state.visualNoteItems, $("visual-point-select").value,
      x / 100, y / 100, $("visual-point-label").value, radius);
    if (!edit) {
      $("visual-note-status").textContent = "That change is invalid. Keep segments nonzero and circles inside the geometry box.";
      return;
    }
    pushVisualNoteUndo();
    state.visualNoteItems[edit.i].objects[edit.j] = edit.object;
    state.visualNoteDirty = true;
    $("visual-note-status").textContent = "Geometry updated. Save the note to keep the change.";
    drawVisualNoteCanvas();
  });
  $("visual-note-title").addEventListener("input", () => { state.visualNoteDirty = true; });
  $("visual-note-undo").addEventListener("click", undoVisualNote);
  $("visual-note-clear").addEventListener("click", () => {
    if (state.visualNoteStrokes.length) pushVisualNoteUndo();
    state.visualNoteStrokes = [];
    state.visualNotePointCount = 0;
    state.visualNoteDirty = true;
    state.activeVisualStroke = null;
    $("visual-note-status").textContent = "Canvas cleared. Save to keep this change.";
    drawVisualNoteCanvas();
  });
  $("visual-note-clear-answer").addEventListener("click", () => {
    if (!state.visualNoteItems.length) return;
    pushVisualNoteUndo();
    state.visualNoteItems = [];
    state.visualNoteDirty = true;
    $("visual-note-status").textContent = "Imported answers removed. Save to keep this change.";
    drawVisualNoteCanvas();
  });
  $("visual-note-canvas").addEventListener("pointerdown", (event) => {
    event.preventDefault();
    if ($("visual-note-tool").value === "geometry") beginGeometryDrag(event);
    else beginVisualNoteStroke(event);
  });
  $("visual-note-canvas").addEventListener("pointermove", (event) => {
    if (activeGeometryDrag) continueGeometryDrag(event);
    else continueVisualNoteStroke(event);
  });
  $("visual-note-canvas").addEventListener("pointerup", (event) => {
    finishGeometryDrag(event);
    state.activeVisualStroke = null;
  });
  $("visual-note-canvas").addEventListener("pointercancel", (event) => {
    finishGeometryDrag(event, true);
    state.activeVisualStroke = null;
  });
  $("visual-note-canvas").addEventListener("lostpointercapture", (event) => {
    finishGeometryDrag(event, true);
    state.activeVisualStroke = null;
  });
  $("visual-note-list").addEventListener("click", async (event) => {
    const open = event.target.closest("[data-visual-note-open]");
    const remove = event.target.closest("[data-visual-note-delete]");
    if (open) {
      await openVisualNote(open.dataset.visualNoteOpen);
    } else if (remove) {
      const deletingActive = state.activeVisualNoteId === remove.dataset.visualNoteDelete;
      const prompt = deletingActive && state.visualNoteDirty
        ? "Delete this visual note and discard unsaved changes?"
        : "Delete this visual note?";
      if (!window.confirm(prompt)) return;
      try {
        await api("/api/visual-notes/delete", {
          method: "POST",
          body: JSON.stringify({ id: remove.dataset.visualNoteDelete }),
        });
        if (deletingActive) {
          state.visualNoteDirty = false;
          newVisualNote();
        }
        await loadVisualNotes();
      } catch (error) {
        toast("Could not delete that visual note.");
      }
    }
  });
  $("visual-note-color").addEventListener("change", (event) => {
    if (!VISUAL_NOTE_COLORS.has(event.target.value)) event.target.value = "#55d6ff";
  });
  window.addEventListener("resize", resizeVisualNoteCanvas);
  $("reminders-clear").addEventListener("click", async () => {
    toast("Ask Helpie to clear reminders in chat, then confirm.");
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
    try { await confirmDataAction("clear_memory", {}); }
    catch (_) { toast("Could not clear memory."); }
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
    if (event.key === "Escape" && !$("screen-region-modal").hidden) {
      closeScreenRegionPicker();
      return;
    }
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
/* ------------------------------------------------------------------ */
/*  Screen overlay (Phase 1)                                           */
/* ------------------------------------------------------------------ */
/* Rendered in a transparent, click-through window that covers the primary
   monitor. It is a visual surface only: no input, no capture, no focus. */
const VISUAL_ANNOTATION_SCHEMA_VERSION = 1;
let overlayAnnotationRevision = -1;
let overlayAnnotationTimer = null;

function clearOverlayAnnotations() {
  if (overlayAnnotationTimer) clearTimeout(overlayAnnotationTimer);
  overlayAnnotationTimer = null;
  document.querySelector(".overlay-annotations")?.remove();
  const announcement = document.querySelector(".overlay-description");
  if (announcement) announcement.textContent = "";
}

function updateOverlayAnnotations(payload, monitor) {
  const revision = Number(payload?.revision ?? 0);
  if (payload?.schema_version !== VISUAL_ANNOTATION_SCHEMA_VERSION) {
    overlayAnnotationRevision = revision;
    clearOverlayAnnotations();
    return;
  }
  if (revision === overlayAnnotationRevision) return;
  overlayAnnotationRevision = revision;
  clearOverlayAnnotations();
  if (!monitor?.primary || monitor.width <= 0 || monitor.height <= 0) return;
  const items = Array.isArray(payload?.items) ? payload.items.slice(0, 3) : [];
  const root = document.querySelector(".overlay-root");
  if (!root || !items.length) return;
  const announcement = root.querySelector(".overlay-description");
  if (announcement) {
    announcement.textContent = `Visual answer: ${items.map((item, index) =>
      `${index + 1}. ${item.kind || "item"}${item.label || item.text || item.expression
        ? `: ${item.label || item.text || item.expression}` : ""}`).join("; ")}`;
  }

  const valid = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "overlay-annotations");
  svg.setAttribute("viewBox", `0 0 ${monitor.width} ${monitor.height}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  const defs = document.createElementNS(svg.namespaceURI, "defs");
  const marker = document.createElementNS(svg.namespaceURI, "marker");
  const markerId = `helpie-arrow-${revision}`;
  marker.setAttribute("id", markerId);
  marker.setAttribute("viewBox", "0 0 10 10");
  marker.setAttribute("refX", "9");
  marker.setAttribute("refY", "5");
  marker.setAttribute("markerWidth", "7");
  marker.setAttribute("markerHeight", "7");
  marker.setAttribute("orient", "auto-start-reverse");
  const arrowHead = document.createElementNS(svg.namespaceURI, "path");
  arrowHead.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
  arrowHead.setAttribute("fill", "#55d6ff");
  marker.appendChild(arrowHead);
  defs.appendChild(marker);
  svg.appendChild(defs);

  const addLabel = (text, x, y) => {
    if (typeof text !== "string" || !text.trim()) return;
    const label = document.createElementNS(svg.namespaceURI, "text");
    label.setAttribute("x", String(Math.max(8, Math.min(monitor.width - 8, x))));
    label.setAttribute("y", String(Math.max(24, Math.min(monitor.height - 15, y))));
    label.setAttribute("class", "overlay-annotation-label");
    label.textContent = text.slice(0, 60);
    svg.appendChild(label);
  };

  for (const [itemIndex, item] of items.entries()) {
    if (!item || typeof item !== "object") continue;
    const firstNode = svg.childNodes.length;
    if (item.kind === "pin" && valid(item.x) && valid(item.y)) {
      const x = item.x * monitor.width;
      const y = item.y * monitor.height;
      const circle = document.createElementNS(svg.namespaceURI, "circle");
      circle.setAttribute("cx", String(x));
      circle.setAttribute("cy", String(y));
      circle.setAttribute("r", "13");
      circle.setAttribute("class", "overlay-annotation-pin");
      svg.appendChild(circle);
      addLabel(item.label, x + 18, y - 15);
    } else if (item.kind === "callout" && valid(item.x) && valid(item.y)
      && Number.isInteger(item.number) && item.number >= 1 && item.number <= 3) {
      const x = item.x * monitor.width;
      const y = item.y * monitor.height;
      const circle = document.createElementNS(svg.namespaceURI, "circle");
      circle.setAttribute("cx", String(x));
      circle.setAttribute("cy", String(y));
      circle.setAttribute("r", "15");
      circle.setAttribute("class", "overlay-annotation-pin");
      svg.appendChild(circle);
      const number = document.createElementNS(svg.namespaceURI, "text");
      number.setAttribute("x", String(x));
      number.setAttribute("y", String(y));
      number.setAttribute("class", "overlay-annotation-number");
      number.setAttribute("text-anchor", "middle");
      number.setAttribute("dominant-baseline", "central");
      number.textContent = String(item.number);
      svg.appendChild(number);
      addLabel(item.label, x + 20, y - 17);
    } else if (item.kind === "equation" && valid(item.x) && valid(item.y)
      && typeof item.text === "string" && item.text.trim() && item.text.length <= 120) {
      const equation = document.createElementNS(svg.namespaceURI, "text");
      equation.setAttribute("x", String(item.x * monitor.width));
      equation.setAttribute("y", String(item.y * monitor.height));
      equation.setAttribute("class", "overlay-annotation-equation");
      equation.textContent = item.text.slice(0, 120);
      svg.appendChild(equation);
    } else if (item.kind === "graph" && valid(item.x) && valid(item.y)
      && valid(item.width) && valid(item.height) && item.width > 0 && item.height > 0
      && item.x + item.width <= 1 && item.y + item.height <= 1
      && typeof item.expression === "string" && item.expression.length <= 96
      && Array.isArray(item.segments)) {
      const segments = [];
      let graphPointBudget = 65;
      for (const segment of item.segments.slice(0, 65)) {
        if (!Array.isArray(segment) || segment.length < 2
          || segment.length > graphPointBudget
          || !segment.every((point) => Array.isArray(point) && point.length === 2
            && valid(point[0]) && valid(point[1]))) continue;
        segments.push(segment);
        graphPointBudget -= segment.length;
      }
      if (!segments.length) continue;
      const x = item.x * monitor.width;
      const y = item.y * monitor.height;
      const width = item.width * monitor.width;
      const height = item.height * monitor.height;
      const frame = document.createElementNS(svg.namespaceURI, "rect");
      frame.setAttribute("x", String(x));
      frame.setAttribute("y", String(y));
      frame.setAttribute("width", String(width));
      frame.setAttribute("height", String(height));
      frame.setAttribute("class", "overlay-annotation-graph-frame");
      svg.appendChild(frame);
      for (let index = 1; index < 4; index += 1) {
        const vertical = document.createElementNS(svg.namespaceURI, "line");
        vertical.setAttribute("x1", String(x + width * index / 4));
        vertical.setAttribute("x2", String(x + width * index / 4));
        vertical.setAttribute("y1", String(y));
        vertical.setAttribute("y2", String(y + height));
        vertical.setAttribute("class", "overlay-annotation-graph-grid");
        svg.appendChild(vertical);
        const horizontal = document.createElementNS(svg.namespaceURI, "line");
        horizontal.setAttribute("x1", String(x));
        horizontal.setAttribute("x2", String(x + width));
        horizontal.setAttribute("y1", String(y + height * index / 4));
        horizontal.setAttribute("y2", String(y + height * index / 4));
        horizontal.setAttribute("class", "overlay-annotation-graph-grid");
        svg.appendChild(horizontal);
      }
      for (const segment of segments) {
        const curve = document.createElementNS(svg.namespaceURI, "polyline");
        const points = segment.map(([px, py]) =>
          `${x + px * width},${y + py * height}`
        ).join(" ");
        curve.setAttribute("points", points);
        curve.setAttribute("class", "overlay-annotation-graph-curve");
        svg.appendChild(curve);
      }
      addLabel(`f(x) = ${item.expression}`, x, y - 10);
    } else if (item.kind === "geometry" && valid(item.x) && valid(item.y)
      && valid(item.width) && valid(item.height) && item.width > 0 && item.height > 0
      && item.x + item.width <= 1 && item.y + item.height <= 1
      && Array.isArray(item.objects) && item.objects.length <= 12
      && Array.isArray(item.constraints) && item.constraints.length <= 8) {
      const x = item.x * monitor.width;
      const y = item.y * monitor.height;
      const width = item.width * monitor.width;
      const height = item.height * monitor.height;
      const positions = [];
      for (const object of item.objects) {
        if (!object || typeof object !== "object") {
          positions.push(null);
          continue;
        }
        const label = typeof object.label === "string" ? object.label.slice(0, 32) : "";
        if (object.kind === "point" && valid(object.x) && valid(object.y)) {
          const px = x + object.x * width;
          const py = y + object.y * height;
          const dot = document.createElementNS(svg.namespaceURI, "circle");
          dot.setAttribute("cx", String(px));
          dot.setAttribute("cy", String(py));
          dot.setAttribute("r", "6");
          dot.setAttribute("class", "overlay-geometry-point");
          svg.appendChild(dot);
          addLabel(label, px + 9, py - 9);
          positions.push({ kind: "point", x: px, y: py });
        } else if (object.kind === "segment" && valid(object.x1) && valid(object.y1)
          && valid(object.x2) && valid(object.y2)
          && (object.x1 !== object.x2 || object.y1 !== object.y2)) {
          const x1 = x + object.x1 * width;
          const y1 = y + object.y1 * height;
          const x2 = x + object.x2 * width;
          const y2 = y + object.y2 * height;
          const line = document.createElementNS(svg.namespaceURI, "line");
          line.setAttribute("x1", String(x1));
          line.setAttribute("y1", String(y1));
          line.setAttribute("x2", String(x2));
          line.setAttribute("y2", String(y2));
          line.setAttribute("class", "overlay-geometry-segment");
          svg.appendChild(line);
          addLabel(label, (x1 + x2) / 2 + 7, (y1 + y2) / 2 - 7);
          positions.push({ kind: "segment", x: (x1 + x2) / 2, y: (y1 + y2) / 2 });
        } else if (object.kind === "circle" && valid(object.cx) && valid(object.cy)
          && valid(object.radius) && object.radius > 0
          && object.cx - object.radius >= 0 && object.cx + object.radius <= 1
          && object.cy - object.radius >= 0 && object.cy + object.radius <= 1) {
          const cx = x + object.cx * width;
          const cy = y + object.cy * height;
          const circle = document.createElementNS(svg.namespaceURI, "ellipse");
          circle.setAttribute("cx", String(cx));
          circle.setAttribute("cy", String(cy));
          circle.setAttribute("rx", String(object.radius * width));
          circle.setAttribute("ry", String(object.radius * height));
          circle.setAttribute("class", "overlay-geometry-circle");
          svg.appendChild(circle);
          addLabel(label, cx + object.radius * width + 6, cy);
          positions.push({ kind: "circle", x: cx, y: cy });
        } else if (object.kind === "polygon" && Array.isArray(object.points)
          && object.points.length >= 3 && object.points.length <= 8
          && object.points.every((point) => Array.isArray(point) && point.length === 2
            && valid(point[0]) && valid(point[1]))) {
          const points = object.points.map(([px, py]) => [x + px * width, y + py * height]);
          const polygon = document.createElementNS(svg.namespaceURI, "polygon");
          polygon.setAttribute("points", points.map(([px, py]) => `${px},${py}`).join(" "));
          polygon.setAttribute("class", "overlay-geometry-polygon");
          svg.appendChild(polygon);
          const center = points.reduce((sum, point) => [sum[0] + point[0] / points.length,
            sum[1] + point[1] / points.length], [0, 0]);
          addLabel(label, center[0] + 7, center[1] - 7);
          positions.push({ kind: "polygon", x: center[0], y: center[1] });
        } else {
          positions.push(null);
        }
      }
      const constraintMarks = {
        horizontal: "↔", vertical: "↕", equal: "=", perpendicular: "⊥", parallel: "∥",
      };
      for (const constraint of item.constraints) {
        if (!constraint || !Object.prototype.hasOwnProperty.call(constraintMarks, constraint.kind)
          || !Array.isArray(constraint.objects)
          || constraint.objects.length !== (constraint.kind === "horizontal"
            || constraint.kind === "vertical" ? 1 : 2)
          || new Set(constraint.objects).size !== constraint.objects.length
          || !constraint.objects.every((index) => Number.isInteger(index)
            && index >= 0 && index < positions.length && positions[index]?.kind === "segment")) continue;
        const linked = constraint.objects.map((index) => positions[index]);
        const mark = document.createElementNS(svg.namespaceURI, "text");
        mark.setAttribute("x", String(linked.reduce((sum, position) => sum + position.x, 0)
          / linked.length));
        mark.setAttribute("y", String(linked.reduce((sum, position) => sum + position.y, 0)
          / linked.length));
        mark.setAttribute("class", "overlay-geometry-constraint");
        mark.textContent = constraintMarks[constraint.kind];
        svg.appendChild(mark);
      }
    } else if (item.kind === "rect" && valid(item.x) && valid(item.y)
      && valid(item.width) && valid(item.height) && item.width > 0 && item.height > 0
      && item.x + item.width <= 1 && item.y + item.height <= 1) {
      const x = item.x * monitor.width;
      const y = item.y * monitor.height;
      const rect = document.createElementNS(svg.namespaceURI, "rect");
      rect.setAttribute("x", String(x));
      rect.setAttribute("y", String(y));
      rect.setAttribute("width", String(item.width * monitor.width));
      rect.setAttribute("height", String(item.height * monitor.height));
      rect.setAttribute("rx", "8");
      rect.setAttribute("class", "overlay-annotation-rect");
      svg.appendChild(rect);
      addLabel(item.label, x, y - 10);
    } else if ((item.kind === "arrow" || item.kind === "underline") && valid(item.x1) && valid(item.y1)
      && valid(item.x2) && valid(item.y2) && (item.x1 !== item.x2 || item.y1 !== item.y2)) {
      const line = document.createElementNS(svg.namespaceURI, "line");
      line.setAttribute("x1", String(item.x1 * monitor.width));
      line.setAttribute("y1", String(item.y1 * monitor.height));
      line.setAttribute("x2", String(item.x2 * monitor.width));
      line.setAttribute("y2", String(item.y2 * monitor.height));
      if (item.kind === "arrow") line.setAttribute("marker-end", `url(#${markerId})`);
      line.setAttribute("class", "overlay-annotation-arrow");
      svg.appendChild(line);
      addLabel(item.label, (item.x1 + item.x2) * monitor.width / 2,
        (item.y1 + item.y2) * monitor.height / 2 - 12);
    }
    if (itemIndex === payload.active_index && svg.childNodes.length > firstNode) {
      const group = document.createElementNS(svg.namespaceURI, "g");
      group.setAttribute("class", "overlay-annotation-active");
      while (svg.childNodes.length > firstNode) group.appendChild(svg.childNodes[firstNode]);
      svg.appendChild(group);
    }
  }
  if (!svg.querySelector("circle, ellipse, rect, line, text, polygon, polyline")) return;
  root.appendChild(svg);
  overlayAnnotationTimer = setTimeout(clearOverlayAnnotations,
    Math.max(1000, Math.min(15000, Number(payload?.duration_ms) || 12000)));
}

function startOverlay() {
  window.helpieOverlayActive = true;
  window.helpieClearAnnotations = () => {
    clearOverlayAnnotations();
    api("/api/overlay/annotations/clear", { method: "POST" }).catch(() => {});
  };
  document.body.classList.add("overlay-mode");
  document.documentElement.classList.add("overlay-mode");
  const root = document.createElement("div");
  root.className = "overlay-root overlay-state-idle";
  root.innerHTML = `
    <div class="overlay-marker" style="left: 0; top: 0; visibility: hidden;">
      <svg class="overlay-cursor" viewBox="0 0 200 220" width="42" height="42" aria-hidden="true">
        <path class="overlay-cursor-shape" d="M37 7 C19 5 6 20 7 39 L16 179 C18 207 47 215 66 195 L103 151 Q110 143 122 140 L168 127 C193 120 195 93 174 79 L55 12 Q46 7 37 7 Z" />
      </svg>
      <span class="overlay-thinking-dots" aria-hidden="true">
        <i></i><i></i><i></i>
      </span>
      <span class="overlay-speaking-orb" aria-hidden="true"><i></i></span>
      <span class="overlay-click-ripple" aria-hidden="true"></span>
      <span class="overlay-tag" role="status" aria-live="polite">Helpie</span>
    </div>
    <div class="overlay-cloud" style="left: 68%; top: 28%;">
      <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
        <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-4.25 5-7 0-1.41-.61-2.75-1.65-3.77z"/>
      </svg>
      <span class="overlay-cloud-tag">Cloud</span>
    </div>
    <div class="overlay-capture-indicator" id="overlay-capture-indicator" data-capture-state="off" role="status" aria-live="polite">
      Screen access off
    </div>
    <div class="overlay-speech-error" role="status" aria-live="polite" hidden></div>
    <div class="overlay-description" role="status" aria-live="polite"></div>
    <div class="voice-banner" aria-hidden="true">
      <span class="voice-banner-logo">H</span>
      <span class="voice-banner-copy"><strong>Helpie</strong><span>Listening to you</span></span>
      <span class="voice-banner-wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>
      <span class="voice-banner-live">LIVE</span>
    </div>
  `;
  document.body.appendChild(root);

  // Escape stops the current task and hides the overlay.
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      stopOverlay();
    }
  });

  // Sync visual state with the backend.
  window.helpieResumeOverlay = () => {
    window.helpieOverlayActive = true;
    pollOverlayState();
  };
  pollOverlayState();
}

function setOverlayState(state, cloudVoiceActive, screenTransfer) {
  const root = document.querySelector(".overlay-root");
  if (!root) return;
  root.className = root.className.replace(/overlay-state-\S+/g, "").trim();
  root.classList.add(`overlay-state-${state}`);
  const remoteFrame = !!screenTransfer?.active && !!screenTransfer?.remote;
  if (cloudVoiceActive || remoteFrame) {
    root.classList.add("overlay-state-cloud-active");
  } else {
    root.classList.remove("overlay-state-cloud-active");
  }
  const cloudTag = root.querySelector(".overlay-cloud-tag");
  if (cloudTag) cloudTag.textContent = remoteFrame ? "Screen frame → cloud" : "Cloud voice";
  const markerTag = root.querySelector(".overlay-tag");
  if (markerTag) {
    markerTag.textContent = state === "thinking" ? "Thinking"
      : state === "speaking" ? "Speaking" : "Helpie";
  }

  const hint = document.querySelector(".overlay-hint");
  const labels = {
    idle: "Idle",
    capturing: "Capturing screen…",
    listening: "Listening\u2026",
    hearing: "Hearing\u2026",
    thinking: "Thinking\u2026",
    speaking: "Speaking\u2026",
    paused: "Paused",
    error: "Error",
    drawing: "Drawing\u2026",
  };
  if (hint) {
    hint.setAttribute("data-state-label", labels[state] || state);
  }
}

function setCaptureIndicator(session, enabled, screenTransfer) {
  const indicator = document.getElementById("overlay-capture-indicator");
  if (!indicator) return;
  let captureState = "off";
  let label = "Screen access off";
  if (screenTransfer?.active) {
    captureState = screenTransfer.remote ? "sending" : "reading";
    label = screenTransfer.remote
      ? "Sending one screen frame to your AI provider"
      : "Reading one screen frame on this PC";
  } else if (session?.state === "active") {
    captureState = "active";
    label = `Screen capture on · local only${session.target ? ` · ${session.target}` : ""}`;
  } else if (session?.state === "warming") {
    captureState = "warming";
    label = "Starting local screen capture…";
  } else if (enabled && session?.state === "unavailable") {
    captureState = "error";
    label = "Screen capture unavailable";
  }
  indicator.dataset.captureState = captureState;
  indicator.textContent = label;
}

async function pollOverlayState() {
  if (window.helpieOverlayPolling) return;
  window.helpieOverlayPolling = true;
  let lastState = null;
  let lastCloudActive = null;
  let lastRemoteFrame = null;
  let lastClickId = null;
  const params = new URLSearchParams(location.search);
  const monitor = {
    left: Number(params.get("screen_x")),
    top: Number(params.get("screen_y")),
    width: Number(params.get("screen_w")),
    height: Number(params.get("screen_h")),
    primary: params.get("screen_primary") === "1",
  };
  const marker = document.querySelector(".overlay-marker");
  const overlayRoot = document.querySelector(".overlay-root");
  if (monitor.primary) overlayRoot?.classList.add("overlay-primary");
  try {
    while (document.querySelector(".overlay-root") && window.helpieOverlayActive) {
      try {
        const data = await api("/api/overlay/state");
        const state = data.state || "idle";
        const voiceBanner = overlayRoot?.querySelector(".voice-banner");
        if (voiceBanner) voiceBanner.style.setProperty("--voice-level", String(Math.max(0, Math.min(1, Number(data.voice_level) || 0))));
        const speechError = overlayRoot?.querySelector(".overlay-speech-error");
        if (speechError) {
          const message = typeof data.speech_error === "string" ? data.speech_error : "";
          speechError.hidden = !monitor.primary || !message;
          if (speechError.textContent !== message) speechError.textContent = message;
        }
        const measuredSpeech = state === "speaking" && typeof data.speech_level === "number" && Number.isFinite(data.speech_level);
        if (overlayRoot) {
          overlayRoot.dataset.speechMeter = measuredSpeech ? "true" : "false";
          overlayRoot.style.setProperty("--speech-level", String(measuredSpeech ? Math.max(0, Math.min(1, data.speech_level)) : 0));
        }
        const cloudActive = !!data.cloud_voice_active;
        const transfer = data.screen_frame_transfer || { active: false, remote: false };
        const remoteCloudActive = cloudActive || (transfer.active && transfer.remote);
        const remoteFrame = !!transfer.active && !!transfer.remote;
        if (state !== lastState || remoteCloudActive !== lastCloudActive || remoteFrame !== lastRemoteFrame) {
          setOverlayState(state, cloudActive, transfer);
          lastState = state;
          lastCloudActive = remoteCloudActive;
          lastRemoteFrame = remoteFrame;
        }
        setCaptureIndicator(data.capture_session, !!data.screen_access_enabled, transfer);
        updateOverlayAnnotations(data.visual_annotations, monitor);
        const point = data.pointer_echo;
        const inMonitor = point && monitor.width > 0 && monitor.height > 0
          && point.x >= monitor.left && point.x < monitor.left + monitor.width
          && point.y >= monitor.top && point.y < monitor.top + monitor.height;
        if (marker) {
          marker.style.visibility = inMonitor ? "visible" : "hidden";
          if (inMonitor) {
            const width = overlayRoot?.clientWidth || window.innerWidth;
            const height = overlayRoot?.clientHeight || window.innerHeight;
            const clickOffset = (2.5 * 96) / 2.54;
            const isCenteredState = state === "thinking" || state === "speaking";
            const anchorX = isCenteredState ? 28 : 9;
            const anchorY = isCenteredState ? 28 : 1.4;
            const targetX = ((point.x - monitor.left) / monitor.width) * width + clickOffset;
            const targetY = ((point.y - monitor.top) / monitor.height) * height + clickOffset;
            const maxLeft = Math.max(0, width - marker.offsetWidth);
            const maxTop = Math.max(0, height - marker.offsetHeight);
            marker.style.left = `${Math.min(maxLeft, Math.max(0, targetX - anchorX))}px`;
            marker.style.top = `${Math.min(maxTop, Math.max(0, targetY - anchorY))}px`;

            const clickId = Number(point.click_id);
            if (lastClickId === null) {
              lastClickId = Number.isFinite(clickId) ? clickId : 0;
            } else if (Number.isFinite(clickId) && clickId > lastClickId) {
              lastClickId = clickId;
              if (state !== "thinking" && state !== "speaking") {
                marker.classList.remove("is-clicking");
                void marker.offsetWidth;
                marker.classList.add("is-clicking");
                clearTimeout(marker._clickTimer);
                marker._clickTimer = setTimeout(() => marker.classList.remove("is-clicking"), 520);
              }
            }
          }
        }
      } catch (e) {
        // Backend may not be ready yet; retry on the next tick.
      }
      await new Promise((r) => setTimeout(r, 20));
    }
  } finally {
    window.helpieOverlayPolling = false;
  }
}

async function stopOverlay() {
  clearOverlayAnnotations();
  try {
    await api("/api/stop", { method: "POST" });
  } catch (e) {
    // Ignore - the overlay will still reset to idle via state sync.
  }
  try {
    await api("/api/overlay/hide", { method: "POST" });
  } catch (e) {
    // Ignore - the tray menu can still hide the overlay.
  }
}

async function boot() {
  const view = new URLSearchParams(location.search).get("view");
  if (view === "voice-close") {
    document.documentElement.classList.add("voice-close-mode");
    document.body.classList.add("voice-close-mode");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "voice-close-button";
    button.setAttribute("aria-label", "Stop and close Helpie companion");
    button.title = "Stop and close Helpie companion";
    button.textContent = "×";
    button.addEventListener("click", async () => {
      button.disabled = true;
      try { await api("/api/stop", { method: "POST" }); }
      catch (_) { button.disabled = false; button.title = "Could not close Helpie. Try again."; }
    });
    document.body.appendChild(button);
    return;
  }
  if (view === "overlay") {
    startOverlay();
    return;
  }
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
