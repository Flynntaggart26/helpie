"""Build the Python backend as a single-file sidecar for the Tauri shell.

Usage:
    python build_sidecar.py

Output:
    src-tauri/binaries/helpie-core-x86_64-pc-windows-msvc.exe

The name must carry the Rust target triple so `bundle.externalBin` can find it.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BINARIES = ROOT / "src-tauri" / "binaries"
TARGET = "x86_64-pc-windows-msvc"

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
]


def main() -> None:
    BINARIES.mkdir(parents=True, exist_ok=True)
    # Build outside OneDrive: syncing locks PyInstaller's scratch folder.
    build_dir = Path(tempfile.gettempdir()) / "helpie-sidecar-build"
    dist_dir = build_dir / "dist"

    # A previous run can still be releasing files for a moment.
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
        "--onefile",
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

    built = dist_dir / "helpie-core.exe"
    final = BINARIES / f"helpie-core-{TARGET}.exe"
    shutil.copy2(built, final)
    size_mb = final.stat().st_size / (1024 * 1024)
    print(f"Sidecar ready: {final} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
