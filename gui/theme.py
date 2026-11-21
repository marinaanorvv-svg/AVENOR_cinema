"""Тема «неон»: шрифты, картинки и оформление ttk (то, что требует tkinter)."""
import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from . import assets_spec as spec
from . import palette as P

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONTS = {}      # ключ -> tkinter.font.Font (заполняется в apply_theme)
_posters = {}   # кеш постеров по (файл, размер)
_images = {}    # кеш картинок: Tk не хранит ссылки сам, без кеша картинки пропадают


def font(key: str):
    """Шрифт по ключу; до apply_theme (например, в тестах) — запасной кортеж."""
    if key in FONTS:
        return FONTS[key]
    size, weight = P.FONT_SPECS[key]
    return ("Helvetica", size, weight)


def text_width(font_obj, text: str) -> int:
    try:
        return font_obj.measure(text)
    except AttributeError:   # запасной вариант без настоящего шрифта
        return len(text) * 8


def load_image(name: str):
    """PNG из gui/assets; None, если файла нет или он не читается (интерфейс тогда рисуется проще)."""
    if name in _images:
        return _images[name]
    path = os.path.join(ASSETS_DIR, name)
    image = None
    if os.path.isfile(path):
        try:
            image = tk.PhotoImage(file=path)
        except tk.TclError:
            image = None
    _images[name] = image
    return image


def _pillow_poster(file, width, height):
    """Постер через Pillow (если установлен): любой формат, обрезка по размеру карточки. Иначе None."""
    try:
        from PIL import Image, ImageOps, ImageTk
        return ImageTk.PhotoImage(ImageOps.fit(Image.open(file).convert("RGBA"), (width, height), Image.LANCZOS))
    except Exception:   # нет Pillow, повреждённый файл, неподдерживаемый формат — не критично
        return None


def _sized_variant(file, size: str):
    """Готовый PNG нужного размера рядом с постером («имя@small.png»); None, если его нет."""
    base, _ = os.path.splitext(str(file))
    path = f"{base}@{size}.png"
    return path if os.path.isfile(path) else None


def load_poster(file, size: str):
    """Постер нужного размера ('small' | 'large') или None.

    С Pillow открывается любой формат и обрезается точно по карточке. Без Pillow берётся готовый PNG «имя@small.png» / «имя@large.png» рядом с постером, а иначе — только PNG и GIF,
    уменьшенные в целое число раз (лишнее обрезается рамкой холста).
    """
    if not file:
        return None
    key = (str(file), size)
    if key not in _posters:
        width, height = spec.POSTER_SIZES[size]
        photo = None
        if os.path.isfile(file):
            photo = _pillow_poster(file, width, height)
            variant = _sized_variant(file, size)
            if photo is None and variant:
                try:
                    photo = tk.PhotoImage(file=variant)
                except tk.TclError:
                    photo = None
            if photo is None and str(file).lower().endswith((".png", ".gif")):
                try:
                    raw = tk.PhotoImage(file=str(file))
                    factor = max(1, min(raw.width() // width, raw.height() // height))
                    photo = raw.subsample(factor) if factor > 1 else raw
                except tk.TclError:
                    photo = None
        _posters[key] = photo
    return _posters[key]


def load_poster_thumb(file):
    """Миниатюра постера (половина размера «small») или None.

    Нельзя делать `load_poster(...).subsample(2)`: при установленном Pillow постер — это ImageTk.PhotoImage,
    у которого нет метода subsample (ошибка «'PhotoImage' object has no attribute 'subsample'»).
    Поэтому миниатюра строится здесь: с Pillow — масштабированием, без него — subsample у tk.PhotoImage.
    """
    if not file:
        return None
    key = (str(file), "thumb")
    if key not in _posters:
        width, height = (v // 2 for v in spec.POSTER_SIZES["small"])
        photo = None
        if os.path.isfile(file):
            photo = _pillow_poster(file, width, height)
            if photo is None:
                variant = _sized_variant(file, "small")
                source = variant or (str(file) if str(file).lower().endswith((".png", ".gif")) else None)
                if source:
                    try:
                        raw = tk.PhotoImage(file=source)
                        factor = max(1, min(raw.width() // width, raw.height() // height))
                        photo = raw.subsample(factor) if factor > 1 else raw
                    except tk.TclError:
                        photo = None
        _posters[key] = photo
    return _posters[key]


def apply_theme(root) -> None:
    """Шрифты, цвета окна и стили ttk для всех экранов."""
    family = P.pick_font_family(tkfont.families(root))
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkCaptionFont",
                 "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont"):
        try:
            tkfont.nametofont(name).configure(family=family, size=10)
        except tk.TclError:
            pass
    for key, (size, weight) in P.FONT_SPECS.items():
        FONTS[key] = tkfont.Font(root=root, family=family, size=size, weight=weight)

    root.configure(bg=P.BG)
    for pattern, value in (            # обычные tk-виджеты берут цвета из «базы настроек»
            ("*Text.background", P.FIELD_BG), ("*Text.foreground", P.TEXT), ("*Text.insertBackground", P.TEXT),
            ("*Text.selectBackground", P.SELECT), ("*Text.highlightThickness", 0), ("*Text.relief", "flat"),
            ("*Toplevel.background", P.PANEL), ("*TCombobox*Listbox.background", P.FIELD_BG),
            ("*TCombobox*Listbox.foreground", P.TEXT), ("*TCombobox*Listbox.selectBackground", P.SELECT),
            ("*TCombobox*Listbox.selectForeground", "#ffffff")):
        root.option_add(pattern, value)

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=P.PANEL, foreground=P.TEXT, fieldbackground=P.FIELD_BG, bordercolor=P.LINE,
                    lightcolor=P.LINE, darkcolor=P.LINE, troughcolor=P.PANEL_ALT, focuscolor=P.PANEL,
                    insertcolor=P.TEXT)
    style.configure("TFrame", background=P.PANEL)
    style.configure("TLabel", background=P.PANEL, foreground=P.TEXT)
    style.configure("Title.TLabel", font=FONTS["title"])
    style.configure("Header.TLabel", font=FONTS["h2"])
    style.configure("Muted.TLabel", foreground=P.MUTED)
    style.configure("TButton", background="#6d2bd9", foreground="#ffffff", bordercolor="#a35cff",
                    lightcolor="#8a3bff", darkcolor="#4b1f9f", focusthickness=0, padding=(14, 7), relief="flat")
    style.map("TButton", background=[("disabled", "#241548"), ("pressed", "#5a22c8"), ("active", "#8a3bff")],
              foreground=[("disabled", "#6f5d99")])
    for name in ("TEntry", "TCombobox"):
        style.configure(name, fieldbackground=P.FIELD_BG, foreground=P.TEXT, bordercolor="#3a2275",
                        lightcolor="#3a2275", darkcolor="#3a2275", insertcolor=P.TEXT, padding=6,
                        arrowcolor=P.MUTED, background="#2a1a4d")
        style.map(name, bordercolor=[("focus", "#c25cff")], lightcolor=[("focus", "#c25cff")],
                  darkcolor=[("focus", "#c25cff")])
    style.map("TCombobox", fieldbackground=[("readonly", P.FIELD_BG)], foreground=[("readonly", P.TEXT)],
              selectbackground=[("readonly", P.FIELD_BG)], selectforeground=[("readonly", P.TEXT)])
    style.configure("Treeview", background="#150b2e", fieldbackground="#150b2e", foreground=P.TEXT,
                    rowheight=30, borderwidth=0)
    style.configure("Treeview.Heading", background="#22124a", foreground=P.MUTED, relief="flat",
                    font=FONTS["bold"], padding=(8, 6))
    style.map("Treeview", background=[("selected", P.SELECT)], foreground=[("selected", "#ffffff")])
    style.map("Treeview.Heading", background=[("active", P.LINE)])
    for name in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):   # на macOS нужны все три имени
        style.configure(name, background="#3a2270", troughcolor=P.PANEL, bordercolor=P.PANEL, lightcolor="#3a2270",
                        darkcolor="#3a2270", arrowcolor=P.MUTED, relief="flat", gripcount=0)
        style.map(name, background=[("active", "#5b2bb5"), ("pressed", "#7c3aed")])
    style.configure("TCheckbutton", background=P.PANEL, foreground=P.TEXT, indicatorbackground=P.FIELD_BG)
    style.map("TCheckbutton", background=[("active", P.PANEL)], indicatorcolor=[("selected", P.ACCENT)])
    style.configure("TSeparator", background=P.LINE)
