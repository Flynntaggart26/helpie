"""Clipboard History Plugin for Helpie."""
import json
import threading
import time
from pathlib import Path


class Plugin:
    def __init__(self):
        self.api = None
        self._history_file = None
        self._history = []
        self._lock = threading.RLock()
        self._watcher_thread = None
        self._stop_watcher = threading.Event()
        self._last_clipboard = ""

    def init(self, api):
        self.api = api
        self._history_file = api.get_data_file("history.json")

        # Move older development builds' history out of the source/plugin folder.
        legacy_history = Path(api._plugin.manifest.path.parent) / "history.json"
        if not self._history_file.exists() and legacy_history.is_file():
            try:
                legacy_data = json.loads(legacy_history.read_text(encoding="utf-8"))
                if isinstance(legacy_data, list):
                    self._history_file.write_text(
                        json.dumps(legacy_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
            except (OSError, json.JSONDecodeError):
                pass

        # Load history
        self._load_history()

        # Register commands
        api.register_command(
            "clipboard_history",
            self.show_history,
            "Show recent clipboard history",
            ["clipboard history", "show clipboard history", "recent clipboard", "panolar geçmişi"]
        )
        api.register_command(
            "clipboard_pin",
            self.pin_item,
            "Pin a clipboard item",
            ["pin clipboard", "pin this clipboard"]
        )
        api.register_command(
            "clipboard_recall",
            self.recall_item,
            "Recall a pinned clipboard item",
            ["recall clipboard", "get pinned clipboard"]
        )
        api.register_command(
            "clipboard_clear",
            self.clear_history,
            "Clear clipboard history",
            ["clear clipboard history", "temizle panolar"]
        )

        # Start clipboard watcher
        self._start_watcher()

        print("[ClipboardHistory] Plugin loaded")

    def shutdown(self):
        self._stop_watcher.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=1.0)
        print("[ClipboardHistory] Plugin unloaded")

    def _load_history(self):
        with self._lock:
            if self._history_file.exists():
                try:
                    self._history = json.loads(self._history_file.read_text(encoding="utf-8"))
                except Exception:
                    self._history = []
            else:
                self._history = []

    def _save_history(self):
        with self._lock:
            try:
                self._history_file.write_text(json.dumps(self._history[-self._get_max_items():], ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

    def _get_max_items(self) -> int:
        return self.api.get_setting("max_items", 50)

    def _start_watcher(self):
        if not self.api.get_setting("auto_save", True):
            return
        self._watcher_thread = threading.Thread(target=self._watch_clipboard, daemon=True, name="clipboard-watcher")
        self._watcher_thread.start()

    def _watch_clipboard(self):
        import clipboard
        while not self._stop_watcher.is_set():
            try:
                text = clipboard.get_text()
                if text and text != self._last_clipboard and text.strip():
                    self._last_clipboard = text
                    self._add_to_history(text)
            except Exception:
                pass
            time.sleep(1.0)

    def _add_to_history(self, text: str):
        with self._lock:
            # Don't add duplicates of the last item
            if self._history and self._history[0].get("text") == text:
                return
            item = {
                "text": text[:500],  # Limit length
                "timestamp": time.time(),
                "pinned": False,
            }
            self._history.insert(0, item)
            self._history = self._history[:self._get_max_items()]
            self._save_history()
            # Emit event for other plugins
            self.api.emit("on_clipboard_change", item)

    # --- Commands ---
    def show_history(self, args: dict = None) -> str:
        with self._lock:
            if not self._history:
                return "Clipboard history is empty."
            lines = ["📋 Clipboard History (recent first):"]
            for i, item in enumerate(self._history[:10]):
                pin = " 📌" if item.get("pinned") else ""
                preview = item["text"][:60].replace("\n", " ") + ("..." if len(item["text"]) > 60 else "")
                ts = time.strftime("%H:%M", time.localtime(item["timestamp"]))
                lines.append(f"  {i+1}. [{ts}]{pin} {preview}")
            return "\n".join(lines)

    def pin_item(self, args: dict = None) -> str:
        # Pin the most recent item
        with self._lock:
            if not self._history:
                return "No clipboard items to pin."
            self._history[0]["pinned"] = True
            self._save_history()
            return f"Pinned: {self._history[0]['text'][:50]}..."

    def recall_item(self, args: dict = None) -> str:
        with self._lock:
            pinned = [item for item in self._history if item.get("pinned")]
            if not pinned:
                return "No pinned items."
            # Recall the most recent pinned
            text = pinned[0]["text"]
            import clipboard
            try:
                clipboard.set_text(text)
            except Exception:
                pass
            self.api.speak(f"Recalled pinned item: {text[:50]}")
            return f"Recalled: {text[:100]}"

    def clear_history(self, args: dict = None) -> str:
        with self._lock:
            # Keep only pinned items
            pinned = [item for item in self._history if item.get("pinned")]
            self._history = pinned
            self._save_history()
            return f"Cleared history. {len(pinned)} pinned item(s) kept."
