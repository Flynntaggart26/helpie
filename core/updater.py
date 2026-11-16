"""Self-update through GitHub Releases.

Flow (same idea as the Plot repo):
  1. VERSION holds the local version.
  2. The latest GitHub release tag (vX.Y.Z) is compared with it.
  3. If newer, the release zip is downloaded, unpacked over the app folder
     (data/ is preserved) and the app restarts itself.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import requests

import os

# Override with the HELPIE_REPO environment variable (e.g. "owner/helpie") when
# running a fork. Defaults to the upstream repository.
REPO = os.environ.get("HELPIE_REPO", "Flynntaggart26/helpie")
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
APP_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = APP_DIR / "VERSION"
SKIP_DIRS = {"data", ".git", "__pycache__", ".venv", "venv", "node_modules"}


def current_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def packaged() -> bool:
    """True when running from the installed build (Tauri shell + PyInstaller sidecar)."""
    return bool(getattr(sys, "frozen", False))


def _parse(version: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", version or "")
    return tuple(int(n) for n in numbers[:4]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return _parse(latest) > _parse(current)


def _is_release_asset(url: str, suffix: str) -> bool:
    """Accept only HTTPS release assets for this configured GitHub repository."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    prefix = f"/{REPO}/releases/download/"
    return (
        parsed.scheme == "https"
        and parsed.hostname == "github.com"
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path.startswith(prefix)
        and parsed.path.lower().endswith(suffix.lower())
        and not parsed.query
        and not parsed.fragment
    )


def check(timeout: float = 8.0) -> dict:
    current = current_version()
    result = {"current": current, "latest": current, "available": False, "url": "", "installer": "", "notes": "", "error": ""}
    try:
        response = requests.get(API_LATEST, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
    except requests.RequestException as exc:
        result["error"] = f"Network error: {exc.__class__.__name__}"
        return result
    if response.status_code == 404:
        result["error"] = "No releases published yet."
        return result
    if response.status_code != 200:
        result["error"] = f"GitHub returned {response.status_code}."
        return result

    data = response.json()
    tag = str(data.get("tag_name", "")).lstrip("vV")
    result["latest"] = tag or current
    result["notes"] = (data.get("body") or "").strip()[:800]
    result["available"] = is_newer(tag, current)
    for asset in data.get("assets", []):
        name = str(asset.get("name", "")).lower()
        if name.endswith(".exe") and "setup" in name:
            result["installer"] = asset.get("browser_download_url", "")
        if name.endswith(".zip") and name.startswith("helpie"):
            result["url"] = asset.get("browser_download_url", "")
    if not result["url"]:
        for asset in data.get("assets", []):
            if str(asset.get("name", "")).lower().endswith(".zip"):
                result["url"] = asset.get("browser_download_url", "")
                break
    return result


def apply(url: str = "") -> dict:
    release = check()
    if packaged():
        installer = release.get("installer", "")
        if not release.get("available") or not _is_release_asset(installer, ".exe"):
            return {"ok": False, "message": "No trusted installer is available for this release."}
        return _apply_installer(installer)
    expected = release.get("url", "")
    if not release.get("available") or not expected or url != expected or not _is_release_asset(expected, ".zip"):
        return {"ok": False, "message": "The update URL did not match the latest trusted release."}
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        payload = io.BytesIO(response.content)
        archive = zipfile.ZipFile(payload)
    except Exception as exc:
        return {"ok": False, "message": f"Download failed: {exc}"}

    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        try:
            for member in archive.infolist():
                target = (temp_path / member.filename).resolve()
                target.relative_to(temp_path.resolve())
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise ValueError("symbolic links are not allowed in updates")
                archive.extract(member, temp_path)
        except Exception as exc:
            return {"ok": False, "message": f"Unpack failed: {exc}"}

        # zip may contain a single top-level folder
        roots = [p for p in temp_path.iterdir() if p.is_dir()]
        source = roots[0] if len(roots) == 1 and not (temp_path / "helpie.py").exists() else temp_path

        copied = 0
        for item in source.rglob("*"):
            if not item.is_file():
                continue
            relative = item.relative_to(source)
            if relative.parts and relative.parts[0] in SKIP_DIRS:
                continue
            destination = APP_DIR / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            copied += 1

    if copied == 0:
        return {"ok": False, "message": "The update package was empty."}

    _restart()
    return {"ok": True, "message": f"Updated ({copied} files). Restarting…"}


def _apply_installer(url: str) -> dict:
    """Installed build: fetch the new setup.exe and let it replace this copy.

    A running exe cannot overwrite itself, so the installer is launched detached
    and waits a few seconds for both Helpie processes to be stopped.
    """
    if not _is_release_asset(url, ".exe"):
        return {"ok": False, "message": "The installer URL is not a trusted GitHub release asset."}

    target = Path(tempfile.gettempdir()) / "Helpie-update-setup.exe"
    try:
        response = requests.get(url, timeout=300, stream=True)
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 18):
                if chunk:
                    handle.write(chunk)
    except Exception as exc:
        return {"ok": False, "message": f"Download failed: {exc}"}

    command = (
        "timeout /t 4 >nul & "
        "taskkill /IM Helpie.exe /F >nul 2>&1 & "
        "taskkill /IM helpie-core.exe /F >nul 2>&1 & "
        f'start "" "{target}" /S'
    )
    subprocess.Popen(
        ["cmd", "/c", command],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )
    return {"ok": True, "message": "Installing the new version. Helpie will restart."}


def _restart() -> None:
    try:
        import wintools

        wintools.close_browser_window()
    except Exception:
        pass
    python = Path(sys.executable)
    windowed = python.with_name("pythonw.exe")
    executable = windowed if windowed.exists() else python
    subprocess.Popen([str(executable), str(APP_DIR / "helpie.py")], cwd=str(APP_DIR),
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    os._exit(0)
