"""Generate the PWA icons in printshare/web/icons (run: python3 scripts/make_icons.py; needs Pillow)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "printshare" / "web" / "icons"
BG = (29, 29, 27)          # --fg of the light theme, reads well on both home screens
ACCENT = (47, 111, 237)    # --accent
LAYER = (236, 236, 234)


def draw(size: int, maskable: bool) -> Image.Image:
    s = 4 * size  # draw large, downsample for smooth edges
    img = Image.new("RGB" if maskable else "RGBA", (s, s), BG if maskable else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if not maskable:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)
    # glyph stays inside the maskable safe zone (inner 80 %)
    u = s * (0.62 if maskable else 0.74) / 10
    cx, top = s / 2, s / 2 - 5 * u
    # nozzle: body + tip
    d.rectangle([cx - 2.2 * u, top, cx + 2.2 * u, top + 2.2 * u], fill=ACCENT)
    d.polygon([(cx - 2.2 * u, top + 2.2 * u), (cx + 2.2 * u, top + 2.2 * u),
               (cx + 0.6 * u, top + 3.6 * u), (cx - 0.6 * u, top + 3.6 * u)], fill=ACCENT)
    # printed layers, the top one still being extruded
    widths = (3.2, 4.6, 4.6, 4.6)
    for i, w in enumerate(widths):
        y = top + 4.6 * u + i * 1.35 * u
        d.rounded_rectangle([cx - w * u, y, cx + w * u, y + 0.95 * u], radius=int(0.45 * u),
                            fill=ACCENT if i == 0 else LAYER)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, False).save(OUT / "icon-192.png")
    draw(512, False).save(OUT / "icon-512.png")
    draw(512, True).save(OUT / "maskable-512.png")
    draw(180, True).save(OUT / "apple-touch-icon.png")  # iOS adds its own rounded corners
    draw(64, False).save(OUT / "favicon.png")


if __name__ == "__main__":
    main()
