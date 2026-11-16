"""Plugin system for Helpie: load and manage trusted in-process plugins."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import jsonschema
import config
from plugin_policy import PLUGIN_RUNTIME_FILES, REVIEWED_BUNDLED_PLUGINS

PLUGINS_DIR = Path(__file__).resolve().parent.parent / "plugins"
PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
SCHEMA_PATH = Path(__file__).resolve().parent / "plugin_schema.json"
SECRET_SETTING = re.compile(r"(?:key|secret|token|password)", re.I)


def _settings_file(plugin: "Plugin") -> Path:
    return config.DATA_DIR / "plugins" / plugin.manifest.name / "settings.json"


def _save_settings_data(manifest: "PluginManifest", settings: dict) -> None:
    path = config.DATA_DIR / "plugins" / manifest.name / "settings.json"
    stored = {}
    for key, value in settings.items():
        if SECRET_SETTING.search(key):
            if value:
                stored[f"{key}_enc"] = config.protect_secret(str(value))
        else:
            stored[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _load_settings(manifest: "PluginManifest") -> dict:
    settings = {key: item.get("default", "") for key, item in manifest.settings_schema.items()}
    path = config.DATA_DIR / "plugins" / manifest.name / "settings.json"
    legacy_path = manifest.path.parent / "settings.json"
    migrating = not path.exists() and legacy_path.exists()
    if migrating:
        path = legacy_path
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    if not isinstance(stored, dict):
        return settings
    for key, value in stored.items():
        if key.endswith("_enc"):
            name = key[:-4]
            if SECRET_SETTING.search(name):
                settings[name] = config.unprotect_secret(str(value or ""))
        elif not SECRET_SETTING.search(key):
            settings[key] = value
        elif key in manifest.settings_schema:
            # Migrate an older plaintext credential to DPAPI on the next save.
            settings[key] = value
    if migrating:
        try:
            _save_settings_data(manifest, settings)
        except RuntimeError:
            # Do not keep legacy credentials in plaintext if DPAPI is unavailable.
            for key, item in manifest.settings_schema.items():
                if SECRET_SETTING.search(key):
                    settings[key] = item.get("default", "")
            legacy_path.unlink(missing_ok=True)
        else:
            legacy_path.unlink(missing_ok=True)
    return settings


def _save_settings(plugin: "Plugin") -> None:
    _save_settings_data(plugin.manifest, plugin.settings)


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
    # Importing a Python plugin executes arbitrary code with Helpie's privileges.
    # Keep it disabled until the user explicitly enables it in the UI.
    enabled: bool = False
    reviewed: bool = False
    error: str = ""
    settings: dict = field(default_factory=dict)

    def load(self) -> bool:
        if self.enabled is False:
            return False
        try:
            plugin_root = self.manifest.path.parent.resolve()
            entry_path = (plugin_root / self.manifest.entry).resolve()
            try:
                entry_path.relative_to(plugin_root)
            except ValueError:
                self.error = "Entry point must stay within the plugin directory"
                return False
            if not entry_path.is_file():
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
        module = self.module
        module_name = getattr(module, "__name__", None)
        if self.instance and hasattr(self.instance, "shutdown"):
            try:
                self.instance.shutdown()
            except Exception:
                pass
        self.instance = None
        self.module = None
        self._api = None
        if module_name and sys.modules.get(module_name) is module:
            del sys.modules[module_name]

    def _make_api(self) -> "PluginAPI":
        return PluginAPI(self)


class PluginAPI:
    """Capability-checked convenience API; plugins still run in-process."""

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
        self._plugin.settings[key] = value
        _save_settings(self._plugin)

    # --- File System ---
    def read_file(self, path: str) -> str:
        self._check("fs.read")
        return Path(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        self._check("fs.write")
        Path(path).write_text(content, encoding="utf-8")

    def get_data_file(self, filename: str) -> Path:
        """Return a path inside this plugin's per-user data directory."""
        self._check("fs.read")
        self._check("fs.write")
        relative = Path(filename)
        if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
            raise ValueError("plugin data filename must be a safe relative path")

        data_root = (config.DATA_DIR / "plugins" / self._plugin.manifest.name).resolve()
        try:
            data_root.relative_to(config.DATA_DIR.resolve())
        except ValueError as exc:
            raise ValueError("plugin data directory escapes Helpie's data directory") from exc
        candidate = (data_root / relative).resolve()
        try:
            candidate.relative_to(data_root)
        except ValueError as exc:
            raise ValueError("plugin data file escapes its plugin data directory") from exc
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate

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
        plugins_root = PLUGINS_DIR.resolve()
        for item in plugins_root.iterdir():
            if not item.is_dir():
                continue
            plugin_dir = item.resolve()
            try:
                plugin_dir.relative_to(plugins_root)
            except ValueError:
                continue
            manifest_path = (plugin_dir / "manifest.json").resolve()
            try:
                manifest_path.relative_to(plugin_dir)
            except ValueError:
                continue
            if not manifest_path.is_file():
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
                    "enabled": False,
                    "trusted": item.name in REVIEWED_BUNDLED_PLUGINS and manifest.name == item.name,
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
            plugins_root = PLUGINS_DIR.resolve()
            for item in plugins_root.iterdir():
                if not item.is_dir():
                    continue
                plugin_dir = item.resolve()
                try:
                    plugin_dir.relative_to(plugins_root)
                except ValueError:
                    results[item.name] = False
                    continue
                manifest_path = (plugin_dir / "manifest.json").resolve()
                try:
                    manifest_path.relative_to(plugin_dir)
                except ValueError:
                    results[item.name] = False
                    continue
                if not manifest_path.is_file():
                    continue
                try:
                    manifest = PluginManifest.from_file(manifest_path)
                    manifest.path = manifest_path
                    if manifest.name in self.plugins:
                        duplicate = self.plugins[manifest.name]
                        duplicate.reviewed = False
                        duplicate.error = "Duplicate plugin identifier; all copies are blocked."
                        results[manifest.name] = False
                        continue
                    reviewed = (
                        item.name in REVIEWED_BUNDLED_PLUGINS
                        and manifest.name == item.name
                    )
                    plugin = Plugin(
                        manifest=manifest,
                        settings=_load_settings(manifest),
                        enabled=False,
                        reviewed=reviewed,
                    )
                    if not reviewed:
                        plugin.error = "Unreviewed plugin blocked; this build allows only reviewed bundled plugins."
                    self.plugins[manifest.name] = plugin
                    # Discovery and manifest validation must never execute plugin code.
                    results[manifest.name] = False
                except Exception as e:
                    results[item.name] = False
            return results

    def get(self, name: str) -> Optional[Plugin]:
        with self._lock:
            return self.plugins.get(name)

    def enable(self, name: str) -> bool:
        with self._lock:
            plugin = self.plugins.get(name)
            if not plugin or not plugin.reviewed:
                return False
            if plugin.enabled:
                return True
            plugin.enabled = True
            if plugin.load():
                return True
            plugin.enabled = False
            plugin.unload()
            return False

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
            if not plugin or not plugin.enabled or not plugin.reviewed:
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
                    "trusted": p.reviewed,
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
