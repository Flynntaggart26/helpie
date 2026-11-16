"""Build Helpie as a standalone Windows .exe using PyInstaller.

Usage:
    python build_exe.py

Output: dist/Helpie/Helpie.exe
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "core"))
from plugin_policy import PLUGIN_RUNTIME_FILES, REVIEWED_BUNDLED_PLUGINS  # noqa: E402

PRIVATE_STATE_NAMES = frozenset({
    "settings.json", "history.json", "memory.json", "notes.md",
    "audit.jsonl", "reminders.json", "routines.json", "port.txt",
    "cookies", "login data", "web data", "local state", "history",
    "network action predictor",
})


def assert_no_local_state(package_dir: Path) -> None:
    """Fail a build if known per-user state leaked into its package tree."""
    package_dir = package_dir.resolve()
    for path in package_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(package_dir)
        parts_lower = tuple(part.lower() for part in relative.parts)
        if (path.name.lower() in PRIVATE_STATE_NAMES and "data" in parts_lower
                and parts_lower.index("data") <= 1):
            raise RuntimeError(f"Refusing package with local state: {relative}")
        if (path.name.lower() in {"history.json", "settings.json"}
                and "plugins" in relative.parts):
            raise RuntimeError(f"Refusing package with plugin runtime state: {relative}")

# Hidden imports that PyInstaller might miss
HIDDEN_IMPORTS = [
    "config",
    "actions",
    "brain",
    "llm",
    "documents",
    "memory",
    "voice",
    "reminders",
    "notify",
    "secrets",
    "autostart",
    "updater",
    "wintools",
    "plugins",
    "routines",
    "audit",
    "history",
    "clipboard",
    "pyaudio",
    "speech_recognition",
    "edge_tts",
    "pygame",
    "pygame.mixer",
    "comtypes",
    "comtypes.client",
    "pycaw",
    "pycaw.pycaw",
    "pvporcupine",
    "keyboard",
    "requests",
    "PIL",
    "PIL.ImageGrab",
    "pypdf",
    "psutil",
    "jsonschema",
    "winreg",
    "ctypes",
    "ctypes.wintypes",
    "http.server",
    "threading",
    "urllib.request",
    "urllib.parse",
    "zipfile",
    "tempfile",
    "subprocess",
    "webbrowser",
]

# Data files to include (source -> dest in bundle)
DATA_FILES = [
    ("VERSION", "."),
    ("ui", "ui"),
    ("core", "core"),
    ("basla.bat", "."),
    ("requirements.txt", "."),
    (".env.example", "."),
]


def build():
    if importlib.util.find_spec("PyInstaller") is None:
        print("ERROR: PyInstaller is missing. Run: python -m pip install -r requirements-build.txt")
        sys.exit(1)
    dist_dir = Path(os.environ.get("HELPIE_BUILD_DIST_DIR", ROOT / "dist")).resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    build_root = Path(tempfile.gettempdir()) / "helpie-exe-build"
    build_root.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name", "Helpie",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--paths",
        str(ROOT / "core"),
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root),
    ]

    # Add hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Add data files
    for src, dst in DATA_FILES:
        src_path = ROOT / src
        if src_path.exists():
            cmd.extend(["--add-data", f"{src_path};{dst}"])

    # Only package reviewed plugin source and manifests. Never copy runtime
    # state such as clipboard history or per-user plugin settings from source.
    for plugin_id in sorted(REVIEWED_BUNDLED_PLUGINS):
        for filename in PLUGIN_RUNTIME_FILES:
            src_path = ROOT / "plugins" / plugin_id / filename
            if not src_path.is_file():
                raise FileNotFoundError(f"Missing bundled plugin file: {src_path}")
            cmd.extend(["--add-data", f"{src_path};plugins/{plugin_id}"])

    # Collect core modules. Plugin entry files are loaded from the bundled
    # reviewed asset list above; do not collect arbitrary plugins as modules.
    cmd.extend(["--collect-submodules", "core"])

    # Entry point
    cmd.append(str(ROOT / "helpie.py"))

    print("Building Helpie.exe...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("Build failed!")
        sys.exit(1)
    assert_no_local_state(dist_dir / "Helpie")
    print("\nBuild successful!")
    print(f"Output: {dist_dir / 'Helpie' / 'Helpie.exe'}")


if __name__ == "__main__":
    build()
