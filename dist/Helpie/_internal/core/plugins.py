"""Plugin system for Helpie: load, manage, and sandbox plugins."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import jsonschema

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA_PATH = Path(__file__).resolve().parent / "plugin_schema.json"


@dataclass
class PluginManifest:
    name: str
    display_name: str
    version: str
    description: str
    author: str
    entry: str
    api_version: str = "1.0"
    permissions: list[str] = field(default_factory=list)
    hooks: dict[str, str] = field(default_factory=dict)
    commands: list[dict] = field(default_factory=list)
    settings_schema: dict = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> "PluginManifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        with SCHEMA_PATH.open(encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(data, schema)
        return cls(**data)


@dataclass
class Plugin:
    manifest: PluginManifest
    module: Any = None
    instance: Any = None
    enabled: bool = True
    error: str = ""
    settings: dict = field(default_factory=dict)

    def load(self) -> bool:
        if self.enabled is False:
            return False
        try:
            entry_path = self.manifest.path.parent / self.manifest.entry
            if not entry_path.exists():
                self.error = f"Entry point not found: {entry_path}"
                return False
            spec = importlib.util.spec_from_file_location(
                f"helpie_plugin_{self.manifest.name}", entry_path
            )
            if not spec or not spec.loader:
                self.error = "Could not create module spec"
                return False
            self.module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = self.module
            spec.loader.exec_module(self.module)

            # Look for Plugin class or create instance
            if hasattr(self.module, "Plugin"):
                self.instance = self.module.Plugin()
            elif hasattr(self.module, "create_plugin"):
                self.instance = self.module.create_plugin()
            else:
                self.instance = self.module

            # Initialize if has init method
            self._api = self._make_api()
            if hasattr(self.instance, "init"):
                self.instance.init(self._api)
            return True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            return False

    def unload(self) -> None:
        if self.instance and hasattr(self.instance, "shutdown"):
            try:
                self.instance.shutdown()
            except Exception:
                pass
        self.instance = None
        self.module = None
        self._api = None

    def _make_api(self) -> "PluginAPI":
        return PluginAPI(self)


class PluginAPI:
    """Sandboxed API exposed to plugins."""

    def __init__(self, plugin: Plugin) -> None:
        self._plugin = plugin
        self._perms = set(plugin.manifest.permissions)
        self._hooks: dict[str, list[Callable]] = {}
        self._commands: dict[str, Callable] = {}
        self._settings = dict(plugin.settings)

    def _check(self, perm: str) -> None:
        if perm not in self._perms:
            raise PermissionError(f"Plugin '{self._plugin.manifest.name}' lacks permission: {perm}")

    # --- Events / Hooks ---
    def on(self, event: str, callback: Callable) -> None:
        self._hooks.setdefault(event, []).append(callback)

    def emit(self, event: str, *args, **kwargs) -> None:
        for cb in self._hooks.get(event, []):
            try:
                cb(*args, **kwargs)
            except Exception:
                pass

    # --- Commands ---
    def register_command(self, name: str, handler: Callable, description: str = "", patterns: list[str] = None) -> None:
        self._check("commands.register")
        self._commands[name] = {"handler": handler, "description": description, "patterns": patterns or []}

    def get_commands(self) -> dict:
        return {name: {"handler": c["handler"], "description": c["description"], "patterns": c["patterns"]} for name, c in self._commands.items()}

    # --- Settings ---
    def get_setting(self, key: str, default: Any = None) -> Any:
        self._check("settings.read")
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._check("settings.write")
        self._settings[key] = value
        # Persist to plugin's settings file
        settings_file = self._plugin.manifest.path.parent / "settings.json"
        try:
            settings_file.write_text(json.dumps(self._settings, indent=2), encoding="utf-8")
        except Exception:
            pass

    # --- File System ---
    def read_file(self, path: str) -> str:
        self._check("fs.read")
        return Path(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        self._check("fs.write")
        Path(path).write_text(content, encoding="utf-8")

    # --- Network ---
    def http_get(self, url: str, headers: dict = None, timeout: float = 10.0) -> dict:
        self._check("net.request")
        import requests
        resp = requests.get(url, headers=headers, timeout=timeout)
        return {"status": resp.status_code, "text": resp.text, "json": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None}

    def http_post(self, url: str, data: dict = None, headers: dict = None, timeout: float = 10.0) -> dict:
        self._check("net.request")
        import requests
        resp = requests.post(url, json=data, headers=headers, timeout=timeout)
        return {"status": resp.status_code, "text": resp.text, "json": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None}

    # --- System ---
    def run_command(self, cmd: list[str], timeout: float = 30.0) -> dict:
        self._check("system.exec")
        import subprocess
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": "timeout", "returncode": -1}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1}

    # --- UI ---
    def show_toast(self, message: str) -> None:
        self._check("ui.render")
        self.emit("ui.toast", message)

    def add_sidebar_item(self, view_id: str, label: str, icon: str = "") -> None:
        self._check("ui.render")
        self.emit("ui.sidebar.add", view_id, label, icon)

    # --- Voice ---
    def speak(self, text: str) -> None:
        self._check("voice.speak")
        self.emit("voice.speak", text)

    # --- Screen ---
    def capture_screen(self) -> bytes:
        self._check("screen.capture")
        import actions
        return actions.capture_screen() or b""


class PluginManager:
    def __init__(self) -> None:
        self.plugins: dict[str, Plugin] = {}
        self._lock = threading.RLock()
        self._core_api = None  # Will be set by server

    def set_core_api(self, api: Any) -> None:
        self._core_api = api

    def discover(self) -> list[dict]:
        results = []
        for item in PLUGINS_DIR.iterdir():
            if not item.is_dir():
                continue
            manifest_path = item / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = PluginManifest.from_file(manifest_path)
                manifest.path = manifest_path
                results.append({
                    "name": manifest.name,
                    "display_name": manifest.display_name,
                    "version": manifest.version,
                    "description": manifest.description,
                    "author": manifest.author,
                    "enabled": True,
                    "error": "",
                })
            except Exception as e:
                results.append({
                    "name": item.name,
                    "display_name": item.name,
                    "version": "0.0.0",
                    "description": f"Invalid manifest: {e}",
                    "author": "",
                    "enabled": False,
                    "error": str(e),
                })
        return results

    def load_all(self) -> dict[str, bool]:
        with self._lock:
            results = {}
            for item in PLUGINS_DIR.iterdir():
                if not item.is_dir():
                    continue
                manifest_path = item / "manifest.json"
                if not manifest_path.exists():
                    continue
                try:
                    manifest = PluginManifest.from_file(manifest_path)
                    manifest.path = manifest_path
                    plugin = Plugin(manifest=manifest)
                    self.plugins[manifest.name] = plugin
                    results[manifest.name] = plugin.load()
                except Exception as e:
                    results[item.name] = False
            return results

    def get(self, name: str) -> Optional[Plugin]:
        with self._lock:
            return self.plugins.get(name)

    def enable(self, name: str) -> bool:
        with self._lock:
            plugin = self.plugins.get(name)
            if not plugin:
                return False
            if plugin.enabled:
                return True
            plugin.enabled = True
            return plugin.load()

    def disable(self, name: str) -> bool:
        with self._lock:
            plugin = self.plugins.get(name)
            if not plugin:
                return False
            if not plugin.enabled:
                return True
            plugin.enabled = False
            plugin.unload()
            return True

    def reload(self, name: str) -> bool:
        with self._lock:
            plugin = self.plugins.get(name)
            if not plugin:
                return False
            plugin.unload()
            return plugin.load()

    def list_plugins(self) -> list[dict]:
        with self._lock:
            result = []
            for p in self.plugins.values():
                commands = []
                if p.instance and hasattr(p, '_api') and p._api:
                    commands = list(p._api._commands.keys())
                result.append({
                    "name": p.manifest.name,
                    "display_name": p.manifest.display_name,
                    "version": p.manifest.version,
                    "description": p.manifest.description,
                    "author": p.manifest.author,
                    "enabled": p.enabled,
                    "error": p.error,
                    "commands": commands,
                })
            return result

    def shutdown(self) -> None:
        with self._lock:
            for plugin in self.plugins.values():
                plugin.unload()


# Global instance
manager = PluginManager()