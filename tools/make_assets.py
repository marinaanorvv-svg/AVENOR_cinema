"""Генератор картинок интерфейса.  Запуск из корня проекта:  python tools/make_assets.py  (нужен Pillow)

Рисует «таблетки» кнопок и полей (со свечением), иконки меню, логотип и две иллюстрации.
Готовые PNG лежат в gui/assets/ — для работы самой программы Pillow не нужен.
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from gui import assets_spec as spec  # noqa: E402

OUT = os.path.join(ROOT, "gui", "assets")
SS = 4   # рисуем в 4 раза крупнее и уменьшаем — получается сглаживание краёв


def rgb(hex_color, alpha=255):
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def vgradient(size, top, bottom, y0=0, y1=None):
    """Вертикальный градиент размера size между строками y0..y1."""
    w, h = size
    y1 = h if y1 is None else y1
    img = Image.new("RGBA", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = min(max((y - y0) / max(y1 - y0, 1), 0), 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(rgb(top), rgb(bottom))))
    return img


# ------------------------------------------------------------------ «таблетки»
PILLS = {
    ("primary", "normal"): dict(top="#e052f5", bottom="#7a35e8", border="#f3a6ff", glow="#c13bff", ga=0.55),
    ("primary", "hover"): dict(top="#ee7bff", bottom="#9250ff", border="#ffd0ff", glow="#e05cff", ga=0.85),
    ("primary", "disabled"): dict(top="#35205f", bottom="#28174a", border="#4b3585", glow=None, ga=0),
    ("ghost", "normal"): dict(top="#150a2e", bottom="#150a2e", border="#6b3fd4", glow="#7c3aed", ga=0.25),
    ("ghost", "hover"): dict(top="#201046", bottom="#201046", border="#b06cff", glow="#a35cff", ga=0.55),
    ("nav_active", "normal"): dict(top="#b13bf0", bottom="#6f2bd9", border="#d98cff", glow="#b13bf0", ga=0.45),
    ("nav_hover", "normal"): dict(top="#1a0e3a", bottom="#1a0e3a", border="#2d1a5c", glow=None, ga=0),
    ("field", "normal"): dict(top="#0f0723", bottom="#0f0723", border="#3a2275", glow=None, ga=0),
    ("field", "focus"): dict(top="#0f0723", bottom="#0f0723", border="#c25cff", glow="#c25cff", ga=0.45),
}


def make_pill(height, p):
    m, r = spec.MARGIN, height // 2
    total_w = 2 * (m + r) + spec.TILE
    W, H = total_w * SS, (height + 2 * m) * SS
    box = (m * SS, m * SS, W - m * SS - 1, (m + height) * SS - 1)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=r * SS, fill=255)
    if p["glow"]:
        glow = Image.new("RGBA", (W, H), rgb(p["glow"], 0))
        glow.putalpha(mask.filter(ImageFilter.GaussianBlur(3.6 * SS)).point(lambda v: int(v * p["ga"])))
        img = Image.alpha_composite(img, glow)
    img.paste(vgradient((W, H), p["top"], p["bottom"], box[1], box[3]), (0, 0), mask)
    border = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(box, radius=r * SS, outline=rgb(p["border"]), width=2 * SS)
    img = Image.alpha_composite(img, border)
    return img.resize((total_w, height + 2 * m), Image.LANCZOS), r


def save_pills():
    m = spec.MARGIN
    for (style, state), p in PILLS.items():
        for height in spec.HEIGHTS:
            img, r = make_pill(height, p)
            cap, h = m + r, img.height
            parts = {"left": img.crop((0, 0, cap, h)), "tile": img.crop((cap, 0, cap + spec.TILE, h)),
                     "right": img.crop((cap + spec.TILE, 0, img.width, h))}
            for part, piece in parts.items():
                piece.save(os.path.join(OUT, spec.pill_asset_name(style, state, height, part)))


# ------------------------------------------------------------------ иконки
def draw_icon(name, color):
    S = 96
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c, w = rgb(color), 7

    def line(pts):
        d.line(pts, fill=c, width=w, joint="curve")
        for x, y in (pts[0], pts[-1]):
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=c)

    if name == "home":
        line([(10, 46), (48, 14), (86, 46)]); line([(22, 40), (22, 82), (74, 82), (74, 40)]); line([(40, 82), (40, 58), (56, 58), (56, 82)])
    elif name == "ticket":
        d.rounded_rectangle((10, 24, 86, 72), radius=10, outline=c, width=w)
        for y in range(30, 68, 12):
            d.line([(62, y), (62, y + 6)], fill=c, width=5)
    elif name == "history":
        d.arc((14, 14, 82, 82), 40, 330, fill=c, width=w); line([(14, 8), (16, 30), (36, 28)]); line([(48, 30), (48, 50), (62, 58)])
    elif name == "film":
        d.rounded_rectangle((14, 14, 82, 82), radius=8, outline=c, width=w)
        line([(34, 14), (34, 82)]); line([(62, 14), (62, 82)])
        for y in (28, 48, 68):
            d.rectangle((20, y - 3, 26, y + 3), fill=c); d.rectangle((70, y - 3, 76, y + 3), fill=c)
    elif name == "seat":
        d.rounded_rectangle((24, 12, 72, 52), radius=10, outline=c, width=w); d.rounded_rectangle((12, 50, 84, 72), radius=8, outline=c, width=w)
        line([(26, 72), (26, 88)]); line([(70, 72), (70, 88)])
    elif name == "calendar":
        d.rounded_rectangle((12, 20, 84, 84), radius=10, outline=c, width=w); line([(12, 42), (84, 42)]); line([(30, 10), (30, 28)]); line([(66, 10), (66, 28)])
        for x in (30, 48, 66):
            d.ellipse((x - 4, 58, x + 4, 66), fill=c)
    elif name == "chart":
        line([(14, 12), (14, 84), (86, 84)])
        for x0, top in ((28, 52), (50, 34), (72, 20)):
            d.rounded_rectangle((x0, top, x0 + 12, 80), radius=3, outline=c, width=6)
    elif name == "users":
        d.ellipse((24, 20, 48, 44), outline=c, width=w); d.arc((10, 52, 62, 108), 180, 360, fill=c, width=w)
        d.ellipse((54, 26, 74, 46), outline=c, width=6); d.arc((50, 56, 90, 104), 200, 360, fill=c, width=6)
    elif name == "user":
        d.ellipse((30, 12, 66, 48), outline=c, width=w); d.arc((14, 56, 82, 128), 190, 350, fill=c, width=w)
    elif name == "dashboard":
        for box in ((12, 12, 44, 52), (52, 12, 84, 36), (12, 60, 44, 84), (52, 44, 84, 84)):
            d.rounded_rectangle(box, radius=8, outline=c, width=w)
    elif name == "search":
        d.ellipse((12, 12, 62, 62), outline=c, width=w); line([(54, 54), (84, 84)])
    elif name == "refund":
        line([(80, 74), (80, 34), (20, 34)]); line([(38, 16), (20, 34), (38, 52)])
    elif name == "shift":
        d.ellipse((12, 12, 84, 84), outline=c, width=w); line([(48, 26), (48, 48), (64, 58)])
    elif name == "logout":
        line([(46, 16), (18, 16), (18, 80), (46, 80)]); line([(36, 48), (84, 48)]); line([(68, 32), (84, 48), (68, 64)])
    return img


def save_icons():
    for name in spec.ICON_NAMES:
        for color_name, color in spec.ICON_COLORS.items():
            draw_icon(name, color).resize((spec.ICON_SIZE,) * 2, Image.LANCZOS).save(
                os.path.join(OUT, spec.icon_asset_name(name, color_name)))


# ------------------------------------------------------------------ логотип и иллюстрации
def font(size, bold=True):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def glow_layer(size, draw_fn, color, alpha, blur):
    mask = Image.new("L", size, 0)
    draw_fn(ImageDraw.Draw(mask))
    layer = Image.new("RGBA", size, rgb(color, 0))
    layer.putalpha(mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * alpha)))
    return layer


def save_logo():
    size = 44 * SS
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    box = (6 * SS, 6 * SS, size - 6 * SS, size - 6 * SS)
    img = Image.alpha_composite(img, glow_layer((size, size), lambda d: d.rounded_rectangle(box, 10 * SS, fill=255), "#d946ef", 0.8, 3 * SS))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, 10 * SS, fill=255)
    img.paste(vgradient((size, size), "#e052f5", "#7a35e8", box[1], box[3]), (0, 0), mask)
    film = draw_icon("film", "#ffffff").resize((22 * SS, 22 * SS), Image.LANCZOS)
    img.alpha_composite(film, ((size - film.width) // 2, (size - film.height) // 2))
    img.resize((44, 44), Image.LANCZOS).save(os.path.join(OUT, "logo_mark.png"))


def save_popcorn():
    W, H = 240 * SS, 270 * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img = Image.alpha_composite(img, glow_layer((W, H), lambda d: d.ellipse((50 * SS, 120 * SS, 190 * SS, 240 * SS), fill=255), "#d946ef", 0.5, 14 * SS))
    d = ImageDraw.Draw(img)
    # стакан с трубочкой (справа)
    cup = [(150, 120), (226, 120), (214, 250), (162, 250)]
    d.polygon([(x * SS, y * SS) for x, y in cup], fill=rgb("#3b1a7a"))
    d.polygon([(x * SS, y * SS) for x, y in [(150, 120), (226, 120), (224, 138), (152, 138)]], fill=rgb("#8a3bff"))
    d.line([(190 * SS, 120 * SS), (200 * SS, 70 * SS), (226 * SS, 62 * SS)], fill=rgb("#f0abfc"), width=7 * SS, joint="curve")
    d.rounded_rectangle((146 * SS, 108 * SS, 230 * SS, 124 * SS), radius=6 * SS, fill=rgb("#6d2bd9"))
    # ведро с полосками (слева)
    top_l, top_r, bot_l, bot_r, y0, y1 = 20, 150, 40, 130, 130, 262
    stripes = 6
    for i in range(stripes):
        def x(t, l, r):
            return l + (r - l) * t
        a, b = i / stripes, (i + 1) / stripes
        poly = [(x(a, top_l, top_r), y0), (x(b, top_l, top_r), y0), (x(b, bot_l, bot_r), y1), (x(a, bot_l, bot_r), y1)]
        d.polygon([(px * SS, py * SS) for px, py in poly], fill=rgb("#ff5cc8" if i % 2 == 0 else "#7b3ff0"))
    d.rounded_rectangle((14 * SS, 122 * SS, 156 * SS, 140 * SS), radius=8 * SS, fill=rgb("#ffd0f0"))
    # попкорн горкой
    rnd = random.Random(5)
    for _ in range(46):
        cx, cy, r = rnd.randint(34, 138), rnd.randint(64, 126), rnd.randint(11, 17)
        cx = min(cx, 150 - (130 - cy) * 0.35) if cy > 100 else cx
        d.ellipse(((cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS), fill=rgb(rnd.choice(["#ffe3f5", "#ffc2ea", "#fff0fa"])))
        d.ellipse(((cx - r * .45) * SS, (cy - r * .6) * SS, (cx + r * .1) * SS, (cy - r * .1) * SS), fill=rgb("#ffffff"))
    img.resize((240, 270), Image.LANCZOS).save(os.path.join(OUT, "popcorn.png"))


def save_hero_placeholder():
    """Запасной вариант картинки входа: нарисованные карточки (если нет постеров)."""
    W, H = 560, 300
    base = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    base = Image.alpha_composite(base, glow_layer(base.size, lambda d: d.ellipse((150 * SS, 70 * SS, 410 * SS, 240 * SS), fill=255), "#b13bf0", 0.4, 24 * SS))

    def card(title, kind, w=170, h=250, top="#4b1f6f", bottom="#2a123f"):
        cw, ch = w * SS, h * SS
        c = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), 16 * SS, fill=255)
        c.paste(vgradient((cw, ch), top, bottom), (0, 0), mask)
        d = ImageDraw.Draw(c)
        cx, cy = cw // 2, int(ch * 0.38)
        ink = rgb("#f1edf7")
        if kind == "rings":
            d.ellipse((cx - 56 * SS, cy - 36 * SS, cx + 4 * SS, cy + 24 * SS), outline=ink, width=4 * SS)
            d.ellipse((cx - 14 * SS, cy - 36 * SS, cx + 46 * SS, cy + 24 * SS), outline=ink, width=4 * SS)
        elif kind == "moon":
            d.ellipse((cx + 8 * SS, cy - 56 * SS, cx + 62 * SS, cy - 2 * SS), fill=ink)
            d.polygon([(0, cy + 6 * SS), (cw // 3, cy - 8 * SS), (cw * 2 // 3, cy + 14 * SS), (cw, cy), (cw, ch * 0.68), (0, ch * 0.68)], fill=rgb("#9c86b9"))
        else:
            d.ellipse((cx - 36 * SS, cy - 40 * SS, cx + 36 * SS, cy + 32 * SS), fill=ink)
            for k in range(4):
                x0 = cx - 54 * SS + k * 36 * SS
                d.rectangle((x0, 0, x0 + 9 * SS, ch * 0.66), fill=rgb("#1a0b33"))
        d.rectangle((0, int(ch * 0.68), cw, ch), fill=rgb("#1a0b33"))
        lines = title.split("\n")
        f = font(15 * SS if len(lines) == 1 else 12 * SS)
        for i, text in enumerate(lines):
            d.text((14 * SS, int(ch * 0.74) + i * 17 * SS), text, font=f, fill=rgb("#ffffff"))
        edge = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle((0, 0, cw - 1, ch - 1), 16 * SS, outline=rgb("#c6b6dd", 150), width=2 * SS)
        return Image.alpha_composite(c, edge)

    left = card("ПРЕСТИЖ", "rings", 150, 220, "#3a1a66", "#1d0b3a").rotate(8, expand=True, resample=Image.BICUBIC)
    right = card("ПОБЕГ ИЗ\nШОУШЕНКА", "bars", 150, 220, "#5a2b8f", "#2a123f").rotate(-8, expand=True, resample=Image.BICUBIC)
    mid = card("ДЮНА", "moon", 180, 260, "#6a2fb0", "#2a123f")
    base.alpha_composite(left, (50 * SS, 48 * SS))
    base.alpha_composite(right, (360 * SS, 48 * SS))
    shadow = glow_layer(base.size, lambda d: d.rounded_rectangle((190 * SS, 24 * SS, 370 * SS, 290 * SS), 16 * SS, fill=255), "#000000", 0.7, 10 * SS)
    base = Image.alpha_composite(base, shadow)
    base.alpha_composite(mid, (190 * SS, 20 * SS))
    base.resize((W, H), Image.LANCZOS).save(os.path.join(OUT, "login_hero.png"))


HERO_POSTERS = ("descendants_3", "coraline_new", "fnaf")   # слева, в центре, справа (папка demo_posters)


def save_hero():
    """Картинка слева на экране входа: три настоящих постера веером. Нет постеров — рисуем карточки."""
    from pathlib import Path
    folder = Path(__file__).resolve().parent.parent / "demo_posters"
    files = [folder / f"{name}.jpg" for name in HERO_POSTERS]
    if not all(f.is_file() for f in files):
        save_hero_placeholder()
        return
    W, H = 560, 300
    base = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    base = Image.alpha_composite(base, glow_layer(base.size, lambda d: d.ellipse((140 * SS, 60 * SS, 420 * SS, 250 * SS), fill=255), "#b13bf0", 0.45, 26 * SS))

    def card(path, w, h):
        cw, ch = w * SS, h * SS
        poster = Image.open(path).convert("RGB")
        poster = ImageOps.fit(poster, (cw, ch), Image.LANCZOS)
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, cw - 1, ch - 1), 16 * SS, fill=255)
        c = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        c.paste(poster, (0, 0), mask)
        edge = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle((0, 0, cw - 1, ch - 1), 16 * SS, outline=rgb("#e7d6ff", 170), width=2 * SS)
        return Image.alpha_composite(c, edge)

    left = card(files[0], 150, 222).rotate(8, expand=True, resample=Image.BICUBIC)
    right = card(files[2], 150, 222).rotate(-8, expand=True, resample=Image.BICUBIC)
    mid = card(files[1], 184, 272)
    base.alpha_composite(left, (44 * SS, 44 * SS))
    base.alpha_composite(right, (366 * SS, 44 * SS))
    shadow = glow_layer(base.size, lambda d: d.rounded_rectangle((188 * SS, 14 * SS, 372 * SS, 290 * SS), 16 * SS, fill=255), "#000000", 0.75, 12 * SS)
    base = Image.alpha_composite(base, shadow)
    base.alpha_composite(mid, (188 * SS, 14 * SS))
    base.resize((W, H), Image.LANCZOS).save(os.path.join(OUT, "login_hero.png"))


POSTER_LOOKS = [("moon", "#6a2fb0", "#2a123f"), ("rings", "#b13bf0", "#3a1a66"), ("bars", "#e052f5", "#4b1f6f"),
                ("sun", "#7c3aed", "#1d0b3a"), ("city", "#d946ef", "#2a123f"), ("wave", "#5a2b8f", "#150a2e")]


def save_poster_placeholders():
    """Абстрактные «афиши» для фильмов без собственного постера (название пишет сама программа)."""
    for index, (kind, top, bottom) in enumerate(POSTER_LOOKS):
        for size_name, (w, h) in spec.POSTER_SIZES.items():
            W, H = w * SS, h * SS
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), 14 * SS, fill=255)
            img.paste(vgradient((W, H), top, bottom), (0, 0), mask)
            d = ImageDraw.Draw(img)
            ink, soft = rgb("#f1edf7"), rgb("#c6b6dd", 200)
            cx, cy, u = W // 2, int(H * 0.36), W // 10
            if kind == "moon":
                d.ellipse((cx - 3 * u, cy - 5 * u, cx + 3 * u, cy + u), fill=ink)
                d.polygon([(0, cy + 2 * u), (W // 3, cy), (W * 2 // 3, cy + 3 * u), (W, cy + u), (W, int(H * .72)), (0, int(H * .72))], fill=soft)
            elif kind == "rings":
                d.ellipse((cx - 5 * u, cy - 3 * u, cx + u, cy + 3 * u), outline=ink, width=u // 2)
                d.ellipse((cx - u, cy - 3 * u, cx + 5 * u, cy + 3 * u), outline=ink, width=u // 2)
            elif kind == "bars":
                for k in range(5):
                    d.rectangle((k * 2 * u + u, 0, k * 2 * u + u + u // 2, int(H * .72)), fill=rgb("#1a0b33"))
                d.ellipse((cx - 3 * u, cy - 3 * u, cx + 3 * u, cy + 3 * u), fill=ink)
            elif kind == "sun":
                for k, r in enumerate((6, 4, 2)):
                    d.ellipse((cx - r * u, cy - r * u, cx + r * u, cy + r * u), outline=ink, width=u // 3)
            elif kind == "city":
                heights = (5, 8, 6, 10, 7, 9, 5, 7)
                for k, hh in enumerate(heights):
                    x0 = k * W // len(heights)
                    d.rectangle((x0, int(H * .72) - hh * u, x0 + W // len(heights) - u // 3, int(H * .72)), fill=rgb("#1a0b33"))
                d.ellipse((cx + u, cy - 5 * u, cx + 5 * u, cy - u), fill=ink)
            else:
                for k in range(4):
                    pts = [(x, int(H * .5) + k * 2 * u + int(math.sin(x / (2.2 * u) + k) * u)) for x in range(0, W, u // 2)]
                    d.line(pts, fill=soft, width=u // 2 + 2)
            d.rectangle((0, int(H * .72), W, H), fill=rgb("#1a0b33"))
            edge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(edge).rounded_rectangle((0, 0, W - 1, H - 1), 14 * SS, outline=rgb("#c6b6dd", 150), width=2 * SS)
            out = Image.alpha_composite(Image.composite(img, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask), edge)
            out.resize((w, h), Image.LANCZOS).save(os.path.join(OUT, spec.poster_placeholder_name(index, size_name)))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    save_pills(); save_icons(); save_logo(); save_popcorn(); save_hero(); save_poster_placeholders()
    missing = [n for n in spec.required_assets() if not os.path.exists(os.path.join(OUT, n))]
    print("готово, файлов:", len(os.listdir(OUT)), "| не хватает:", missing or "нет")
