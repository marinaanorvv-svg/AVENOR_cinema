"""Перечень и параметры картинок интерфейса.

Модуль не импортирует tkinter: им пользуются и программа, и генератор картинок
(tools/make_assets.py), и тесты (проверяют, что все нужные файлы на месте).
"""
import math

MARGIN = 8          # прозрачное поле вокруг «таблетки» под свечение, px
TILE = 16           # ширина повторяющегося среднего куска, px
HEIGHTS = (36, 44)  # высоты кнопок и полей, px
PILL_STATES = {
    "primary": ("normal", "hover", "disabled"),   # главная кнопка (градиент с свечением)
    "ghost": ("normal", "hover"),                 # второстепенная кнопка (контур)
    "nav_active": ("normal",),                    # выбранный пункт меню
    "nav_hover": ("normal",),                     # пункт меню под курсором
    "field": ("normal", "focus"),                 # поле ввода
}
PARTS = ("left", "tile", "right")
ICON_NAMES = ("home", "ticket", "history", "film", "seat", "calendar", "chart", "users", "user", "logout", "dashboard", "search", "refund", "shift")
ICON_COLORS = {"dim": "#b9a5ee", "bright": "#ffffff"}
ICON_SIZE = 24
DECOR = ("logo_mark.png", "popcorn.png", "login_hero.png")
POSTER_SIZES = {"small": (150, 210), "large": (190, 266)}   # карточка афиши и панель подробностей
POSTER_PLACEHOLDERS = 6                                    # сколько разных картинок-заглушек для фильмов без постера


def pill_asset_name(style: str, state: str, height: int, part: str) -> str:
    return f"pill_{style}_{state}_{height}_{part}.png"


def poster_placeholder_name(index: int, size: str) -> str:
    """Заглушка постера: номер берётся по кругу, так что подходит любой id фильма."""
    return f"poster_ph_{index % POSTER_PLACEHOLDERS}_{size}.png"


def icon_asset_name(name: str, color: str) -> str:
    return f"icon_{name}_{color}.png"


def pill_geometry(inner_width: int, height: int) -> tuple[int, int, int]:
    """(число средних кусков, полная ширина, полная высота) «таблетки» с полями под свечение.

    Таблетка собирается из левого края, N одинаковых средних кусков и правого края,
    поэтому ширина округляется вверх до кратной TILE (прирост меньше TILE px).
    """
    radius = height // 2
    tiles = max(0, math.ceil((inner_width - 2 * radius) / TILE))
    return tiles, 2 * (MARGIN + radius) + tiles * TILE, height + 2 * MARGIN


def required_assets() -> list[str]:
    names = list(DECOR)
    for style, states in PILL_STATES.items():
        for state in states:
            for height in HEIGHTS:
                names += [pill_asset_name(style, state, height, part) for part in PARTS]
    for icon in ICON_NAMES:
        names += [icon_asset_name(icon, color) for color in ICON_COLORS]
    names += [poster_placeholder_name(i, size) for i in range(POSTER_PLACEHOLDERS) for size in POSTER_SIZES]
    return names
