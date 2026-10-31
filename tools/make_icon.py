"""Draws the launcher icon (faceted blue gem on a navy tile) into mcd_loader/assets."""
import os

from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(__file__), "..", "mcd_loader", "assets")
S = 1024  # draw large, downscale for smooth edges


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def draw(size=S):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # navy tile with vertical gradient
    tile = Image.new("RGBA", (size, size))
    td = ImageDraw.Draw(tile)
    for y in range(size):
        td.line([(0, y), (size, y)], fill=lerp((36, 40, 66, 255), (18, 19, 30, 255), y / size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255)
    img.paste(tile, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, size - 7, size - 7], radius=int(size * 0.215), outline=(61, 109, 242, 120), width=10)

    # glow behind the gem
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([size * .22, size * .22, size * .78, size * .78], fill=(61, 109, 242, 150))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(size * 0.08)))

    cx, top, mid, bot = size / 2, size * 0.22, size * 0.42, size * 0.80
    left, right = size * 0.20, size * 0.80
    crown_l, crown_r = size * 0.33, size * 0.67
    t = lambda *p: [tuple(x) for x in p]  # noqa: E731
    facets = [
        (t((left, mid), (crown_l, top), (cx, mid)), (111, 147, 255)),
        (t((crown_l, top), (crown_r, top), (cx, mid)), (160, 186, 255)),
        (t((crown_r, top), (right, mid), (cx, mid)), (86, 126, 248)),
        (t((left, mid), (cx, mid), (cx, bot)), (61, 109, 242)),
        (t((cx, mid), (right, mid), (cx, bot)), (38, 76, 196)),
    ]
    for poly, color in facets:
        d.polygon(poly, fill=color + (255,))
    for a, b in [((left, mid), (right, mid)), ((crown_l, top), (cx, mid)), ((crown_r, top), (cx, mid)),
                 ((cx, mid), (cx, bot))]:
        d.line([a, b], fill=(220, 230, 255, 160), width=int(size * 0.008))
    # sparkle
    sx, sy, r = size * 0.74, size * 0.24, size * 0.07
    d.polygon([(sx, sy - r), (sx + r * .22, sy - r * .22), (sx + r, sy), (sx + r * .22, sy + r * .22),
               (sx, sy + r), (sx - r * .22, sy + r * .22), (sx - r, sy), (sx - r * .22, sy - r * .22)],
              fill=(255, 255, 255, 235))
    return img


def draw_mark(size=S):
    """The gem alone on a transparent background (splash and sidebar logo)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, top, mid, bot = size / 2, size * 0.10, size * 0.38, size * 0.95
    left, right = size * 0.02, size * 0.98
    crown_l, crown_r = size * 0.24, size * 0.76
    t = lambda *p: [tuple(x) for x in p]  # noqa: E731
    for poly, color in [
        (t((left, mid), (crown_l, top), (cx, mid)), (111, 147, 255)),
        (t((crown_l, top), (crown_r, top), (cx, mid)), (160, 186, 255)),
        (t((crown_r, top), (right, mid), (cx, mid)), (86, 126, 248)),
        (t((left, mid), (cx, mid), (cx, bot)), (45, 100, 240)),
        (t((cx, mid), (right, mid), (cx, bot)), (30, 70, 200)),
    ]:
        d.polygon(poly, fill=color + (255,))
    for a, b in [((left, mid), (right, mid)), ((crown_l, top), (cx, mid)), ((crown_r, top), (cx, mid)),
                 ((cx, mid), (cx, bot))]:
        d.line([a, b], fill=(220, 230, 255, 150), width=int(size * 0.01))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    draw_mark().resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "mark.png"))
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "logo.png"))
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(OUT, "launcher.ico"),
                                               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
                                                      (256, 256)])


if __name__ == "__main__":
    main()
