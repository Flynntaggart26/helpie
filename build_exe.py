"""Build Helpie as a standalone Windows .exe using PyInstaller.

Usage:
    python build_exe.py

Output: dist/Helpie/Helpie.exe
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

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
    ("plugins", "plugins"),
    ("data", "data"),
    ("basla.bat", "."),
    ("requirements.txt", "."),
    (".env.example", "."),
]


def build():
    # Find pyinstaller executable
    pyinstaller_exe = None
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path, "pyinstaller.exe")
        if os.path.exists(candidate):
            pyinstaller_exe = candidate
            break
    if not pyinstaller_exe:
        # Common installation locations
        candidates = [
            r"C:\Users\egecr\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\pyinstaller.exe",
            os.path.join(sys.prefix, "Scripts", "pyinstaller.exe"),
            os.path.join(sys.prefix, "bin", "pyinstaller"),
        ]
        for c in candidates:
            if os.path.exists(c):
                pyinstaller_exe = c
                break
    if not pyinstaller_exe:
        print("ERROR: pyinstaller not found. Run: pip install pyinstaller")
        sys.exit(1)
    cmd = [
        pyinstaller_exe,
        "--name", "Helpie",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
    ]

    # Add hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Add data files
    for src, dst in DATA_FILES:
        src_path = ROOT / src
        if src_path.exists():
            cmd.extend(["--add-data", f"{src_path};{dst}"])

    # Collect all submodules from core and plugins
    cmd.extend(["--collect-submodules", "core"])
    cmd.extend(["--collect-submodules", "plugins"])

    # Entry point
    cmd.append(str(ROOT / "helpie.py"))

    print("Building Helpie.exe...")
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("Build failed!")
        sys.exit(1)
    print("\nBuild successful!")
    print(f"Output: {ROOT / 'dist' / 'Helpie' / 'Helpie.exe'}")


if __name__ == "__main__":
    build()
