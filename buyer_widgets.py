"""Общие элементы экранов покупателя: стена карточек фильмов (афиша, главная) и подписи."""
import tkinter as tk

from services import clock, movie_service

from . import neon
from . import palette as P
from . import theme
from . import assets_spec as spec
from .formatting import day_caption, format_duration, format_price

TILE_W, GAP, PAD = 188, 16, 10
POSTER_W, POSTER_H = spec.POSTER_SIZES["small"]
TEXT_H = 158
TILE_H = PAD + POSTER_H + TEXT_H + PAD
HEADING_H = 40


def columns_for(width: int) -> int:
    return max(1, (width - GAP) // (TILE_W + GAP))


def tile_position(index: int, width: int, top: int) -> tuple[int, int]:
    """Левый верхний угол карточки номер index в сетке, начинающейся на высоте top."""
    columns = columns_for(width)
    left = max(GAP, (width - columns * (TILE_W + GAP) + GAP) // 2)
    row, col = divmod(index, columns)
    return left + col * (TILE_W + GAP), top + row * (TILE_H + GAP)


class DayBar(tk.Frame):
    """Ряд кнопок-дат: «Все даты», «Сегодня», «Завтра», «18.11 вт»… Выбранная подсвечена.

    on_pick(day_iso или None) вызывается при выборе; None — «Все даты».
    """

    def __init__(self, parent, on_pick, bg=P.PANEL):
        super().__init__(parent, bg=bg)
        self.on_pick, self._bg, self.days, self.selected = on_pick, bg, [], None
        self.buttons = {}

    def set_days(self, days, selected=None):
        self.days = list(days)
        self.selected = selected if selected in self.days else None
        self._rebuild()

    def pick(self, day):
        """Меняем только вид кнопок (без пересоздания: нажатая кнопка ещё обрабатывает щелчок)."""
        self.selected = day
        for key, button in self.buttons.items():
            button.look = "primary" if key == day else "ghost"
            button._draw()
        self.on_pick(day)

    def _rebuild(self):
        for child in self.winfo_children():
            child.destroy()
        self.buttons = {}
        today = clock.now().date()
        for day in [None] + self.days:
            text = "Все даты" if day is None else day_caption(day, today)
            button = neon.NeonButton(self, text, lambda d=day: self.pick(d), height=34, bg=self._bg,
                                     style="primary" if day == self.selected else "ghost")
            button.pack(side="left", padx=(0, 6))
            self.buttons[day] = button


def next_session_text(movie: dict) -> str:
    return f"Ближайший: {day_caption(movie['next_date'], clock.now().date())}, {movie['next_time']}"


class MovieWall(tk.Canvas):
    """Стена карточек фильмов с заголовками разделов и вертикальной прокруткой.

    set_sections([(заголовок или None, [фильмы])], empty_text) перерисовывает стену;
    нажатие на карточку вызывает on_open(movie_id).
    """

    def __init__(self, parent, on_open):
        super().__init__(parent, bg=P.PANEL, bd=0, highlightthickness=0)
        self.on_open = on_open
        self._sections, self._empty, self._images, self._max_rows = [], "", [], None
        self.bind("<Configure>", lambda event: self._draw())
        self.bind("<Enter>", self._bind_wheel)
        self.bind("<Leave>", self._unbind_wheel)

    def set_sections(self, sections, empty_text="Сейчас нет доступных фильмов.", max_rows=None):
        """max_rows — показывать в каждом разделе не больше стольких рядов карточек (на главной — один ряд)."""
        self._max_rows = max_rows
        self._sections = [(title, list(movies)) for title, movies in sections if movies]
        self._empty = empty_text
        self._draw()

    def card_count(self) -> int:
        return sum(len(movies) for _, movies in self._sections)

    def _draw(self):
        self.delete("all")
        self._images = []
        width = max(self.winfo_width(), TILE_W + 2 * GAP)
        view_h = self.winfo_height()
        y = GAP
        for section, (title, movies) in enumerate(self._sections):
            if title:
                self.create_text(GAP + 4, y + 4, text=title, anchor="nw", fill=P.TEXT, font=theme.font("h2"))
                y += HEADING_H
            if self._max_rows:
                movies = movies[:columns_for(width) * self._max_rows]
            for index, movie in enumerate(movies):
                x, top = tile_position(index, width, y)
                self._draw_card(section, x, top, movie)
            rows = (len(movies) + columns_for(width) - 1) // columns_for(width)
            y += rows * (TILE_H + GAP) + GAP
        if not self._sections:
            self.create_text(width // 2, max(view_h, 200) // 2, text=self._empty, fill=P.MUTED,
                             font=theme.font("h2"), width=width - 4 * GAP, justify="center")
        full_h = max(y, view_h)
        self.configure(scrollregion=(0, 0, width, full_h))
        neon.draw_stars(self, width, full_h, 60 + full_h // 14)

    def _draw_card(self, section, x, y, movie):
        tag = f"card{section}_{movie['id']}"
        frame = self.create_polygon(P.rounded_points(x, y, x + TILE_W, y + TILE_H, 16), smooth=True,
                                    fill=P.PANEL_ALT, outline=P.LINE, width=1, tags=(tag,))
        left, inner = x + PAD, TILE_W - 2 * PAD
        image, _ = neon.poster_image(movie_service.poster_file(movie["poster_path"]), movie["id"], "small")
        if image is not None:
            self._images.append(image)
            self.create_image(x + (TILE_W - POSTER_W) // 2, y + PAD, image=image, anchor="nw", tags=(tag,))
        badge = "НОВИНКА" if movie.get("is_new") else ("ХИТ" if movie.get("popularity", 0) >= 3 else "")
        if badge:
            self.create_polygon(P.rounded_points(x + PAD + 6, y + PAD + 6, x + PAD + 6 + 74, y + PAD + 28, 10),
                                smooth=True, fill=P.VIOLET, outline=P.ACCENT_SOFT, tags=(tag,))
            self.create_text(x + PAD + 6 + 37, y + PAD + 17, text=badge, fill="#ffffff", font=theme.font("small"),
                             tags=(tag,))
        meta = f"{movie['genre_name']} · {format_duration(movie['duration'])} · {movie['age_rating']}"
        lines = ((movie["title"], P.TEXT, "nav_bold"), (meta, P.ACCENT_SOFT, "small"),
                 (next_session_text(movie), P.MUTED, "small"),
                 (f"от {format_price(movie['min_price'])} · сеансов: {movie['sessions']}", P.TEXT, "bold"))
        top = y + PAD + POSTER_H + 6
        for text, color, font_key in lines:      # каждая строка начинается под предыдущей — наложения быть не может
            item = self.create_text(left, top, text=text, anchor="nw", fill=color, width=inner,
                                    font=theme.font(font_key), tags=(tag,))
            box = self.bbox(item)
            top = (box[3] if box else top + 18) + 5
        self.tag_bind(tag, "<Button-1>", lambda event, mid=movie["id"]: self.on_open(mid))
        self.tag_bind(tag, "<Enter>", lambda event, item=frame: self._hover(item, True))
        self.tag_bind(tag, "<Leave>", lambda event, item=frame: self._hover(item, False))

    def _hover(self, item, inside):
        self.itemconfigure(item, outline=P.ACCENT if inside else P.LINE, width=2 if inside else 1)
        self.configure(cursor="hand2" if inside else "arrow")

    # ------------------------------------------------------------------ прокрутка колёсиком
    def _bind_wheel(self, event=None):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(sequence, self._on_wheel)

    def _unbind_wheel(self, event=None):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.unbind_all(sequence)

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            units = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        self.yview_scroll(units, "units")
