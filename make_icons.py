"""Generate the Tauri icon set from assets/helpie.png."""
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "assets" / "helpie.png"
OUT = ROOT / "src-tauri" / "icons"

SIZES = {
    "32x32.png": 32,
    "128x128.png": 128,
    "128x128@2x.png": 256,
    "icon.png": 512,
    "Square150x150Logo.png": 150,
    "Square44x44Logo.png": 44,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    image = Image.open(SRC).convert("RGBA")

    # Square canvas so nothing gets stretched in the Windows installer.
    side = max(image.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2), image)

    for name, size in SIZES.items():
        canvas.resize((size, size), Image.LANCZOS).save(OUT / name)

    canvas.resize((256, 256), Image.LANCZOS).save(
        OUT / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icons written to {OUT}")


if __name__ == "__main__":
    main()
