"""Палитра «неон» и чистые функции оформления (без tkinter — проверяются обычными тестами)."""
import random

BG = "#0a0516"            # фон окна
SIDEBAR = "#0d0720"       # боковое меню
PANEL = "#130a28"         # карточки и рабочая область
PANEL_ALT = "#1b0f38"     # поля, строки
FIELD_BG = "#0f0723"      # внутри полей ввода (должен совпадать с картинками pill_field_*)
LINE = "#2d1a5c"          # тонкие линии
TEXT = "#f5eeff"
MUTED = "#b4a4da"      # чуть светлее: лучше читается на тёмном фоне
ERROR = "#ff8fa6"
ACCENT = "#d946ef"        # неоновый розово-фиолетовый
ACCENT_SOFT = "#f0abfc"
VIOLET = "#7c3aed"
SELECT = "#5b2bb5"        # выделение строк

FONT_CANDIDATES = ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Noto Sans", "Ubuntu", "DejaVu Sans", "Arial")
FONT_SPECS = {"body": (11, "normal"), "bold": (11, "bold"), "nav": (10, "normal"), "nav_bold": (10, "bold"),
              "small": (10, "normal"), "h2": (15, "bold"), "title": (22, "bold"), "hero": (26, "bold"), "logo": (17, "bold")}


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def blend(color_a: str, color_b: str, t: float) -> str:
    """Смесь двух цветов: t=0 — первый, t=1 — второй. Нужна для имитации свечения без прозрачности."""
    a, b = hex_to_rgb(color_a), hex_to_rgb(color_b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def pick_font_family(available, candidates=FONT_CANDIDATES, default="Helvetica") -> str:
    """Первый из желаемых шрифтов, который есть в системе."""
    lower = {name.lower(): name for name in available}
    for candidate in candidates:
        if candidate.lower() in lower:
            return lower[candidate.lower()]
    return default


def rounded_points(x1, y1, x2, y2, radius):
    """Точки скруглённого прямоугольника для create_polygon(..., smooth=True)."""
    r = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    return [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r, x2, y2 - r,
            x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
            x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]


def star_points(width, height, count, seed=7):
    """Звёзды для фона: (x, y, размер, цвет). Одно зерно — одно и то же небо при каждой перерисовке."""
    rnd = random.Random(seed)
    colors = ("#2a1d52", "#3a2870", "#4b3a80", "#6b4fa8")   # приглушённые точки: фон не отвлекает от содержимого
    return [(rnd.randrange(width), rnd.randrange(height), 1, rnd.choice(colors))
            for _ in range(count)]
