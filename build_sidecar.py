"""Build the Python backend as a folder-based sidecar for the Tauri shell.

Usage:
    python build_sidecar.py

Output:
    src-tauri/sidecar/helpie-core/helpie-core.exe  (+ _internal/)

A folder build is deliberate: a onefile exe unpacks ~80 MB into %TEMP% on every
launch, which antivirus and Defender ASR rules commonly block on managed
machines, and it makes startup slow.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SIDECAR = ROOT / "src-tauri" / "sidecar" / "helpie-core"

sys.path.insert(0, str(ROOT))
from build_exe import HIDDEN_IMPORTS  # noqa: E402

# Everything the app reads at runtime. `data/` is deliberately absent: it holds
# the user's settings and encrypted API key and must never ship in a build.
DATA_FILES = [
    ("VERSION", "."),
    ("ui", "ui"),
    ("core", "core"),
    ("plugins", "plugins"),
    ("requirements.txt", "."),
]

EXCLUDES = [
    "tkinter",
    "matplotlib",
    "pandas",
    "scipy",
    "numpy",
    "IPython",
    "notebook",
    "pytest",
    "torch",
    "pocketsphinx",
]

# SpeechRecognition ships Sphinx models (~31 MB) that are only used by
# `recognize_sphinx`; Helpie only calls `recognize_google`. Pillow's AVIF
# decoder is equally unreachable. Dropping them keeps the download small.
PRUNE_DIRS = ["pocketsphinx-data"]
PRUNE_FILES = ["_avif*.pyd"]


def prune(target: Path) -> int:
    """Delete bundled data the app never reads. Returns the bytes saved."""
    saved = 0
    for name in PRUNE_DIRS:
        for path in target.rglob(name):
            if path.is_dir():
                saved += sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                shutil.rmtree(path, ignore_errors=True)
    for name in PRUNE_FILES:
        for path in target.rglob(name):
            saved += path.stat().st_size
            path.unlink(missing_ok=True)
    return saved


def main() -> None:
    SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    # Build outside OneDrive: syncing locks PyInstaller's scratch folder.
    build_dir = Path(tempfile.gettempdir()) / "helpie-sidecar-build"
    dist_dir = build_dir / "dist"

    for _ in range(6):
        shutil.rmtree(build_dir, ignore_errors=True)
        if not build_dir.exists():
            break
        time.sleep(1.5)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--name",
        "helpie-core",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir / "work"),
        "--specpath",
        str(build_dir),
    ]

    for module in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", module])
    for module in EXCLUDES:
        cmd.extend(["--exclude-module", module])
    for src, dest in DATA_FILES:
        path = ROOT / src
        if path.exists():
            cmd.extend(["--add-data", f"{path};{dest}"])

    cmd.extend(["--collect-submodules", "core"])
    cmd.extend(["--collect-submodules", "plugins"])
    cmd.append(str(ROOT / "helpie.py"))

    print("Building the Helpie backend sidecar...")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("Sidecar build failed.")
        sys.exit(1)

    built = dist_dir / "helpie-core"
    if not (built / "helpie-core.exe").exists():
        print(f"Sidecar build produced no exe in {built}")
        sys.exit(1)

    for _ in range(6):
        shutil.rmtree(SIDECAR, ignore_errors=True)
        if not SIDECAR.exists():
            break
        time.sleep(1)
    shutil.copytree(built, SIDECAR)

    saved = prune(SIDECAR)

    total = sum(f.stat().st_size for f in SIDECAR.rglob("*") if f.is_file())
    print(
        f"Sidecar ready: {SIDECAR} ({total / (1024 * 1024):.1f} MB, "
        f"pruned {saved / (1024 * 1024):.1f} MB)"
    )


if __name__ == "__main__":
    main()
