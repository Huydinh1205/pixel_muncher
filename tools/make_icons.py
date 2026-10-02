"""Draw the app icon and export PNG / ICO / ICNS. Run: python tools/make_icons.py

Concept: a 3x3 grid of map tiles. Tiles in the top-left are aerial-photo greens,
tiles in the bottom-right are classification colours, and the diagonal tiles
are split between the two (orthomosaic in, classified map out).
"""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets"
S = 1024 * 4  # supersample, then downscale for smooth edges


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # background: rounded square with vertical gradient
    grad = Image.new("RGBA", (S, S))
    top, bottom = (63, 140, 102), (30, 74, 54)
    gd = ImageDraw.Draw(grad)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(top, bottom, y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    photo = [(150, 186, 120), (112, 156, 92), (176, 196, 140), (128, 170, 104), (98, 140, 84)]
    classes = [(230, 159, 0), (86, 180, 233), (240, 228, 66), (204, 121, 167), (0, 190, 140)]
    margin, gap = int(S * 0.17), int(S * 0.035)
    cell = (S - 2 * margin - 2 * gap) // 3
    rad = int(cell * 0.18)
    k = 0
    for j in range(3):
        for i in range(3):
            x0, y0 = margin + i * (cell + gap), margin + j * (cell + gap)
            box = [x0, y0, x0 + cell, y0 + cell]
            tile_mask = Image.new("L", (S, S), 0)
            ImageDraw.Draw(tile_mask).rounded_rectangle(box, radius=rad, fill=255)
            if i + j < 2:
                fill = Image.new("RGBA", (S, S), photo[k % len(photo)] + (255,))
                img.paste(fill, (0, 0), tile_mask)
            elif i + j > 2:
                fill = Image.new("RGBA", (S, S), classes[k % len(classes)] + (255,))
                img.paste(fill, (0, 0), tile_mask)
            else:  # diagonal: split tile, photo top-left, class bottom-right
                a = Image.new("RGBA", (S, S), photo[k % len(photo)] + (255,))
                b = Image.new("RGBA", (S, S), classes[k % len(classes)] + (255,))
                tri = Image.new("L", (S, S), 0)
                ImageDraw.Draw(tri).polygon([(x0 + cell, y0), (x0 + cell, y0 + cell), (x0, y0 + cell)], fill=255)
                img.paste(a, (0, 0), tile_mask)
                both = Image.new("L", (S, S), 0)
                both.paste(tile_mask, (0, 0), tri)
                img.paste(b, (0, 0), both)
            k += 1
    # subtle white outline on the middle tile to suggest "processing"
    cx0 = margin + cell + gap
    d.rounded_rectangle([cx0, cx0, cx0 + cell, cx0 + cell], radius=rad, outline=(255, 255, 255, 230),
                        width=int(S * 0.012))
    return img.resize((1024, 1024), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    big = draw()
    big.save(OUT / "icon-1024.png")
    for size in (512, 192, 180, 64, 32):
        big.resize((size, size), Image.LANCZOS).save(OUT / f"icon-{size}.png")
    big.save(OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / "icon.icns")
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
