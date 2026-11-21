"""Фирменные виджеты неонового стиля: кнопки-«таблетки», поля ввода, панели, пункты меню.

«Таблетки» собираются из готовых PNG (левый край + повторяющийся средний кусок + правый край),
поэтому растягиваются до любой ширины, а сглаженные края и свечение нарисованы заранее.
"""
import tkinter as tk

from . import assets_spec as spec
from . import palette as P
from . import theme

_FALLBACK_FILL = P.PANEL_ALT


def draw_pill(canvas, style, state, height, inner_width, x=0, y=0, tag="pill"):
    """Рисует «таблетку» на холсте. Возвращает (ширина, высота) вместе с полями под свечение."""
    tiles, total_w, total_h = spec.pill_geometry(inner_width, height)
    parts = [theme.load_image(spec.pill_asset_name(style, state, height, part)) for part in spec.PARTS]
    if None in parts:   # нет картинок — рисуем простую заливку, чтобы программа оставалась рабочей
        m = spec.MARGIN
        canvas.create_rectangle(x + m, y + m, x + total_w - m, y + total_h - m, fill=_FALLBACK_FILL,
                                outline=P.LINE, tags=tag)
        return total_w, total_h
    left, tile, right = parts
    cap = spec.MARGIN + height // 2
    canvas.create_image(x, y, image=left, anchor="nw", tags=tag)
    for i in range(tiles):
        canvas.create_image(x + cap + i * spec.TILE, y, image=tile, anchor="nw", tags=tag)
    canvas.create_image(x + cap + tiles * spec.TILE, y, image=right, anchor="nw", tags=tag)
    return total_w, total_h


def draw_logo(canvas, x, cy):
    """Значок и название кинотеатра «AVENOR»; (x, cy) — левый край и вертикальный центр."""
    mark = theme.load_image("logo_mark.png")
    if mark:
        canvas.create_image(x, cy, image=mark, anchor="w")
    face = theme.font("logo")
    left = x + (54 if mark else 0)
    canvas.create_text(left, cy, text="AVE", anchor="w", fill=P.TEXT, font=face)
    canvas.create_text(left + theme.text_width(face, "AVE") + 2, cy, text="NOR", anchor="w", fill="#f06bff", font=face)


def draw_stars(canvas, width, height, count=90, tag="stars"):
    canvas.delete(tag)
    for x, y, size, color in P.star_points(width, height, count):
        canvas.create_oval(x, y, x + size, y + size, fill=color, outline="", tags=tag)
    canvas.tag_lower(tag)


class NeonButton(tk.Canvas):
    """Кнопка-«таблетка». style: 'primary' (градиент со свечением) или 'ghost' (контур)."""

    def __init__(self, parent, text, command=None, style="primary", height=44, width=None, icon=None,
                 bg=P.PANEL, clickable=True):
        self.label, self.on_click, self.look, self.pill_h, self.icon_name = text, command, style, height, icon
        self.enabled, self.hovered, self.clickable = True, False, clickable
        icon_w = 26 if icon else 0
        self.inner = width or theme.text_width(theme.font("bold"), text) + 52 + icon_w
        _, total_w, total_h = spec.pill_geometry(self.inner, height)
        super().__init__(parent, width=total_w, height=total_h, bg=bg, bd=0, highlightthickness=0,
                         cursor="hand2" if clickable else "arrow")
        if clickable:
            self.bind("<Enter>", lambda event: self._hover(True))
            self.bind("<Leave>", lambda event: self._hover(False))
            self.bind("<ButtonRelease-1>", self._released)
        self._draw()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._draw()

    def set_text(self, text: str) -> None:
        self.label = text
        self._draw()

    def _hover(self, value):
        self.hovered = value and self.enabled
        self._draw()

    def _released(self, event):
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        if inside and self.enabled and self.on_click:
            self.on_click()

    def _draw(self):
        self.delete("all")
        states = spec.PILL_STATES[self.look]
        if not self.enabled and "disabled" in states:
            state = "disabled"
        elif self.hovered and "hover" in states:
            state = "hover"
        else:
            state = "normal"
        total_w, total_h = draw_pill(self, self.look, state, self.pill_h, self.inner)
        color = "#7b68a6" if not self.enabled else ("#ffffff" if self.look == "primary" else P.TEXT)
        face, cx, cy = theme.font("bold"), total_w // 2, total_h // 2
        icon = theme.load_image(spec.icon_asset_name(self.icon_name, "bright")) if self.icon_name else None
        if icon:
            start = cx - (26 + theme.text_width(face, self.label)) // 2
            self.create_image(start, cy, image=icon, anchor="w")
            self.create_text(start + 26, cy, text=self.label, anchor="w", fill=color, font=face)
        else:
            self.create_text(cx, cy, text=self.label, fill=color, font=face)


class NeonEntry(tk.Canvas):
    """Поле ввода в рамке-«таблетке», подсвечивается при фокусе. Сам текст — в self.entry."""

    def __init__(self, parent, textvariable, width=320, show="", bg=P.PANEL, height=44):
        self.pill_h, self.inner = height, width
        _, total_w, total_h = spec.pill_geometry(width, height)
        super().__init__(parent, width=total_w, height=total_h, bg=bg, bd=0, highlightthickness=0, cursor="xterm")
        self.entry = tk.Entry(self, textvariable=textvariable, show=show, bd=0, highlightthickness=0, relief="flat",
                              bg=P.FIELD_BG, fg=P.TEXT, insertbackground=P.TEXT, selectbackground=P.SELECT,
                              font=theme.font("body"))
        pad = spec.MARGIN + height // 2 - 4
        self.create_window(pad, total_h // 2, window=self.entry, anchor="w", width=total_w - 2 * pad)
        self._draw("normal")
        self.entry.bind("<FocusIn>", lambda event: self._draw("focus"))
        self.entry.bind("<FocusOut>", lambda event: self._draw("normal"))
        self.bind("<Button-1>", lambda event: self.entry.focus_set())

    def _draw(self, state):
        self.delete("pill")
        draw_pill(self, "field", state, self.pill_h, self.inner)
        self.tag_lower("pill")

    def focus_set(self):
        self.entry.focus_set()


class RoundedPanel(tk.Canvas):
    """Скруглённая панель со светящейся рамкой. Содержимое кладётся в panel.body."""

    def __init__(self, parent, fill=P.PANEL, border="#4a2a9a", radius=22, pad=16, bg=P.BG, glow=False):
        super().__init__(parent, bg=bg, bd=0, highlightthickness=0)
        self.fill, self.border, self.radius, self.pad, self.glow, self.bg_color = fill, border, radius, pad, glow, bg
        self.body = tk.Frame(self, bg=fill)
        self._window = self.create_window(pad, pad, window=self.body, anchor="nw")
        self.bind("<Configure>", self._redraw)

    def _redraw(self, event=None):
        width, height = self.winfo_width(), self.winfo_height()
        if width < 8 or height < 8:
            return
        self.delete("shape")
        points = P.rounded_points(4, 4, width - 4, height - 4, self.radius)
        if self.glow:   # «свечение» — две полупрозрачные по виду обводки, смешанные с фоном
            for line_width, mix in ((6, 0.8), (4, 0.55)):
                self.create_polygon(points, smooth=True, fill="", outline=P.blend(self.border, self.bg_color, mix),
                                    width=line_width, tags="shape")
        self.create_polygon(points, smooth=True, fill=self.fill, outline=self.border, width=1, tags="shape")
        self.tag_lower("shape")
        self.coords(self._window, self.pad, self.pad)
        self.itemconfigure(self._window, width=width - 2 * self.pad, height=height - 2 * self.pad)


class NavItem(tk.Canvas):
    """Пункт бокового меню: иконка + название, подсветка при наведении и выбранный вид."""

    def __init__(self, parent, text, icon, command, width=214, bg=P.SIDEBAR):
        self.label, self.icon_name, self.on_click, self.inner, self.pill_h = text, icon, command, width, 44
        self.active = self.hovered = False
        _, total_w, total_h = spec.pill_geometry(width, 44)
        super().__init__(parent, width=total_w, height=total_h, bg=bg, bd=0, highlightthickness=0, cursor="hand2")
        self.bind("<Enter>", lambda event: self._hover(True))
        self.bind("<Leave>", lambda event: self._hover(False))
        self.bind("<ButtonRelease-1>", lambda event: self.on_click())
        self._draw()

    def set_active(self, active: bool) -> None:
        self.active = active
        self._draw()

    def _hover(self, value):
        self.hovered = value
        self._draw()

    def _draw(self):
        self.delete("all")
        if self.active:
            draw_pill(self, "nav_active", "normal", self.pill_h, self.inner)
        elif self.hovered:
            draw_pill(self, "nav_hover", "normal", self.pill_h, self.inner)
        lit = self.active or self.hovered
        icon = theme.load_image(spec.icon_asset_name(self.icon_name, "bright" if lit else "dim"))
        cy, x = (self.pill_h + 2 * spec.MARGIN) // 2, spec.MARGIN + 18
        if icon:
            self.create_image(x, cy, image=icon, anchor="w")
        self.create_text(x + 36, cy, text=self.label, anchor="w", fill=P.TEXT if lit else P.MUTED,
                         font=theme.font("nav_bold" if self.active else "nav"))


def poster_image(file, index, size="small"):
    """Картинка постера нужного размера: настоящая или заглушка. Возвращает (картинка | None, это_заглушка)."""
    real = theme.load_poster(file, size)
    if real is not None:
        return real, False
    return theme.load_image(spec.poster_placeholder_name(index, size)), True


def poster_thumb(file, index):
    """Миниатюра постера (половина «small») или её заглушка; безопасна и с Pillow, и без него. None, если картинок нет."""
    real = theme.load_poster_thumb(file)
    if real is not None:
        return real
    placeholder = theme.load_image(spec.poster_placeholder_name(index, "small"))
    return placeholder.subsample(2) if placeholder is not None else None


class PosterView(tk.Canvas):
    """Постер фильма: настоящая картинка или красивая заглушка с названием."""

    def __init__(self, parent, size="small", bg=P.PANEL_ALT):
        self.size_name = size
        self.poster_w, self.poster_h = spec.POSTER_SIZES[size]
        super().__init__(parent, width=self.poster_w, height=self.poster_h, bg=bg, bd=0, highlightthickness=0,
                         cursor="hand2")
        self.shown = None   # ссылка на показанную картинку (иначе Tk её «забудет»)

    def show(self, file, title, index):
        """file — путь к постеру (или None), title — название для заглушки, index — номер заглушки (id фильма)."""
        self.delete("all")
        real = theme.load_poster(file, self.size_name)
        cx, cy = self.poster_w // 2, self.poster_h // 2
        if real is not None:
            self.shown = real
            self.create_image(cx, cy, image=real, anchor="center")
            return
        self.shown = theme.load_image(spec.poster_placeholder_name(index, self.size_name))
        if self.shown is not None:
            self.create_image(0, 0, image=self.shown, anchor="nw")
        self.create_text(cx, int(self.poster_h * 0.86), text=title, width=self.poster_w - 20, fill=P.TEXT,
                         font=theme.font("nav_bold"), justify="center")

    def clear(self):
        self.delete("all")
        self.shown = None
