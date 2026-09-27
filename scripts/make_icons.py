"""Generate the PWA icons (printshare/web/icons) and the native app icons (mobile/assets).

Run: python3 scripts/make_icons.py (needs Pillow).
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "printshare" / "web" / "icons"
MOBILE = ROOT / "mobile" / "assets"
BG = (29, 29, 27)          # --fg of the light theme, reads well on both home screens
ACCENT = (47, 111, 237)    # --accent
LAYER = (236, 236, 234)


def draw(size: int, maskable: bool, *, glyph: float | None = None, bg: bool = True,
         mono: bool = False) -> Image.Image:
    """maskable: square full-bleed background; glyph: glyph height as share of the icon."""
    s = 4 * size  # draw large, downsample for smooth edges
    img = Image.new("RGBA", (s, s), BG if maskable and bg else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if not maskable and bg:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)
    accent, layer = ((255, 255, 255), (255, 255, 255)) if mono else (ACCENT, LAYER)
    # glyph stays inside the maskable safe zone (inner 80 %)
    u = s * (glyph or (0.62 if maskable else 0.74)) / 10
    cx, top = s / 2, s / 2 - 5 * u
    # nozzle: body + tip
    d.rectangle([cx - 2.2 * u, top, cx + 2.2 * u, top + 2.2 * u], fill=accent)
    d.polygon([(cx - 2.2 * u, top + 2.2 * u), (cx + 2.2 * u, top + 2.2 * u),
               (cx + 0.6 * u, top + 3.6 * u), (cx - 0.6 * u, top + 3.6 * u)], fill=accent)
    # printed layers, the top one still being extruded
    widths = (3.2, 4.6, 4.6, 4.6)
    for i, w in enumerate(widths):
        y = top + 4.6 * u + i * 1.35 * u
        d.rounded_rectangle([cx - w * u, y, cx + w * u, y + 0.95 * u], radius=int(0.45 * u),
                            fill=accent if i == 0 else layer)
    img = img.resize((size, size), Image.LANCZOS)
    return img.convert("RGB") if maskable and bg else img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    draw(192, False).save(OUT / "icon-192.png")
    draw(512, False).save(OUT / "icon-512.png")
    draw(512, True).save(OUT / "maskable-512.png")
    draw(180, True).save(OUT / "apple-touch-icon.png")  # iOS adds its own rounded corners
    draw(64, False).save(OUT / "favicon.png")

    # native app (Expo): iOS masks the corners itself; Android adaptive icons get a 66 % safe zone
    MOBILE.mkdir(parents=True, exist_ok=True)
    draw(1024, True, glyph=0.6).save(MOBILE / "icon.png")
    draw(1024, True, glyph=0.42, bg=False).save(MOBILE / "android-icon-foreground.png")
    draw(1024, True, glyph=0.42, bg=False, mono=True).save(MOBILE / "android-icon-monochrome.png")
    Image.new("RGB", (1024, 1024), BG).save(MOBILE / "android-icon-background.png")
    draw(512, True, glyph=0.9, bg=False).save(MOBILE / "splash-icon.png")
    draw(64, False).save(MOBILE / "favicon.png")


if __name__ == "__main__":
    main()
