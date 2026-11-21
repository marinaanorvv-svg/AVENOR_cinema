"""Афиша: стена постеров на выбранный день. Постер переворачивается и показывает описание; кнопка «Выбрать сеанс» открывает страницу фильма."""
import tkinter as tk
from tkinter import ttk

from services import movie_service, session_service
from services.errors import ServiceError

from . import neon
from . import palette as P
from . import theme
from .common import guarded
from .formatting import format_duration, normalize_date_input, shift_date, today_ru
from .formatting import short_description, upcoming_times
from . import assets_spec as spec

TILE_W, GAP = 176, 14          # ширина плитки и промежуток между плитками, px
PAD = 8                        # поле внутри плитки, px
POSTER_W, POSTER_H = spec.POSTER_SIZES["small"]
TEXT_H = 78                    # место под название и время сеансов
TILE_H = PAD + POSTER_H + TEXT_H + PAD
DESC_LIMIT = 230               # описание на обратной стороне постера обрезается
FLIP_STEPS, FLIP_DELAY = 6, 16  # переворот: шагов на половину оборота и пауза между шагами, мс


def tile_origin(index: int, width: int) -> tuple[int, int, int]:
    """(x, y, колонок) левого верхнего угла плитки номер index на холсте шириной width.

    Плитки стоят в сетке с одинаковым шагом, поэтому постеры не могут налезть друг на друга.
    """
    columns = max(1, (width - GAP) // (TILE_W + GAP))
    left = max(GAP, (width - columns * (TILE_W + GAP) + GAP) // 2)
    row, col = divmod(index, columns)
    return left + col * (TILE_W + GAP), GAP + row * (TILE_H + GAP), columns


class ScheduleFrame(tk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent, bg=P.PANEL)
        self.user = user
        self.on_open = None    # MainFrame подставляет переход на страницу фильма: on_open(movie_id, date_iso)
        self.date_var, self.error_var, self.status_var = tk.StringVar(value=today_ru()), tk.StringVar(), tk.StringVar()
        self._board, self._images = [], []
        self._flipped = set()        # id фильмов, у которых показана обратная сторона (описание)
        self._tiles = {}             # id фильма -> (x, y, элемент рамки)
        self._busy, self._generation = set(), 0
        self._build_ui()
        self.load()

    # ------------------------------------------------------------------ интерфейс
    def _label(self, parent, font_key="body", color=P.TEXT, bg=P.PANEL, **options):
        return tk.Label(parent, font=theme.font(font_key), fg=color, bg=bg, **options)

    def _build_ui(self):
        head = tk.Frame(self, bg=P.PANEL)
        head.pack(fill="x")
        titles = tk.Frame(head, bg=P.PANEL)
        titles.pack(side="left")
        self._label(titles, "title", text="Афиша").pack(anchor="w")
        self._label(titles, "small", P.MUTED, text="Нажмите на постер — он перевернётся и покажет описание").pack(anchor="w")
        nav = tk.Frame(head, bg=P.PANEL)
        nav.pack(side="right")
        neon.NeonButton(nav, "◀", lambda: self._shift(-1), style="ghost", height=36, width=36, bg=P.PANEL).pack(side="left")
        self.date_entry = neon.NeonEntry(nav, self.date_var, width=120, height=36, bg=P.PANEL)
        self.date_entry.pack(side="left", padx=4)
        self.date_entry.entry.bind("<Return>", lambda event: self.load())
        neon.NeonButton(nav, "▶", lambda: self._shift(1), style="ghost", height=36, width=36, bg=P.PANEL).pack(side="left")
        neon.NeonButton(nav, "Сегодня", self._today, style="ghost", height=36, bg=P.PANEL).pack(side="left", padx=(8, 0))
        self._label(self, "small", P.ERROR, textvariable=self.error_var, anchor="w").pack(fill="x")

        wall = tk.Frame(self, bg=P.PANEL)
        wall.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas = tk.Canvas(wall, bg=P.PANEL, bd=0, highlightthickness=0)
        scroll = ttk.Scrollbar(wall, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self._draw())
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)
        self._label(self, "small", P.MUTED, textvariable=self.status_var, anchor="w").pack(fill="x", pady=(6, 0))

    # ------------------------------------------------------------------ данные
    def load(self):
        try:
            self.date_var.set(normalize_date_input(self.date_var.get()))
        except ServiceError as exc:
            self.error_var.set(str(exc))
            return
        ok, board = guarded(self, session_service.get_schedule_for_date, self.user, self.date_var.get())
        if not ok:
            return
        self.error_var.set("")
        self._board = board
        self._flipped = set()
        if board:
            self.status_var.set(f"Фильмов в афише на {self.date_var.get()}: {len(board)}")
        else:
            hint = "На эту дату сеансов нет. Выберите другую дату."
            if self.user.role == "admin":
                hint += " Сеансы добавляются в разделе «Сеансы»."
            self.status_var.set(hint)
        self._draw()

    def _shift(self, days):
        try:
            self.date_var.set(shift_date(self.date_var.get(), days))
        except ServiceError as exc:
            self.error_var.set(str(exc))
            return
        self.load()

    def _today(self):
        self.date_var.set(today_ru())
        self.load()

    # ------------------------------------------------------------------ стена постеров
    def _draw(self):
        canvas = self.canvas
        width, view_h = max(canvas.winfo_width(), TILE_W + 2 * GAP), canvas.winfo_height()
        canvas.delete("all")
        self._generation += 1        # прерывает незаконченные анимации переворота
        self._busy = set()
        self._images, self._tiles = [], {}     # ссылки на картинки: без них Tk «забудет» постеры
        rows_used = 0
        for index, entry in enumerate(self._board):
            x, y, columns = tile_origin(index, width)
            self._draw_tile(x, y, entry)
            rows_used = index // columns + 1
        total = GAP + rows_used * (TILE_H + GAP)
        full_h = max(total, view_h)
        canvas.configure(scrollregion=(0, 0, width, full_h))
        neon.draw_stars(canvas, width, full_h, 70 + full_h // 14)

    def _entry(self, movie_id):
        return next((e for e in self._board if e["movie"]["id"] == movie_id), None)

    def _draw_tile(self, x, y, entry):
        """Плитка фильма: рамка и одна из двух сторон — постер или описание."""
        canvas, movie = self.canvas, entry["movie"]
        tag = f"film{movie['id']}"
        frame = canvas.create_polygon(P.rounded_points(x, y, x + TILE_W, y + TILE_H, 14), smooth=True,
                                      fill=P.PANEL_ALT, outline=P.LINE, width=1, tags=(tag, f"frame{movie['id']}"))
        self._tiles[movie["id"]] = (x, y, frame)
        self._draw_face(movie["id"])
        canvas.tag_bind(tag, "<Button-1>", lambda event, mid=movie["id"]: self._clicked(mid, event))
        canvas.tag_bind(tag, "<Enter>", lambda event, item=frame: self._hover(item, True))
        canvas.tag_bind(tag, "<Leave>", lambda event, item=frame: self._hover(item, False))

    def _draw_face(self, movie_id):
        """Рисует содержимое плитки: спереди постер, сзади описание и кнопка «Выбрать сеанс»."""
        canvas, entry = self.canvas, self._entry(movie_id)
        x, y, _ = self._tiles[movie_id]
        movie, tag, face = entry["movie"], f"film{movie_id}", f"face{movie_id}"
        canvas.delete(face)
        tags, inner = (tag, face), TILE_W - 2 * PAD - 4
        left = x + PAD + 2
        meta = f"{movie['genre_name']} · {format_duration(movie['duration'])} · {movie['age_rating']}"
        if movie_id in self._flipped:
            canvas.create_text(left, y + PAD + 4, text=movie["title"], anchor="nw", fill=P.TEXT, width=inner,
                               font=theme.font("nav_bold"), tags=tags)
            canvas.create_text(left, y + PAD + 44, text=meta, anchor="nw", fill=P.ACCENT_SOFT, width=inner,
                               font=theme.font("small"), tags=tags)
            canvas.create_text(left, y + PAD + 82, text=short_description(movie["description"]), anchor="nw",
                               fill=P.TEXT, width=inner, font=theme.font("small"), tags=tags)
            canvas.create_text(left, y + TILE_H - 76, text=upcoming_times(entry["sessions"]), anchor="nw",
                               fill=P.MUTED, width=inner, font=theme.font("small"), tags=tags)
            button = canvas.create_polygon(P.rounded_points(left, y + TILE_H - 50, left + inner, y + TILE_H - 14, 18),
                                           smooth=True, fill=P.VIOLET, outline=P.ACCENT_SOFT, width=1,
                                           tags=(tag, face, f"go{movie_id}"))
            canvas.create_text(left + inner // 2, y + TILE_H - 32, text="Выбрать сеанс", fill="#ffffff",
                               font=theme.font("bold"), tags=(tag, face, f"go{movie_id}"))
            return
        image, _ = neon.poster_image(movie_service.poster_file(movie["poster_path"]), movie_id, "small")
        if image is not None:
            self._images.append(image)
            canvas.create_image(left, y + PAD, image=image, anchor="nw", tags=tags)
        top = y + PAD + POSTER_H + 6
        canvas.create_text(left, top, text=movie["title"], anchor="nw", fill=P.TEXT, width=inner,
                           font=theme.font("nav_bold"), tags=tags)
        canvas.create_text(left, top + 38, text=meta, anchor="nw", fill=P.MUTED, width=inner,
                           font=theme.font("small"), tags=tags)
        canvas.create_text(left, top + 56, text=upcoming_times(entry["sessions"]), anchor="nw", fill=P.ACCENT_SOFT,
                           width=inner, font=theme.font("small"), tags=tags)

    def _hover(self, item, inside):
        self.canvas.itemconfigure(item, outline=P.ACCENT if inside else P.LINE, width=2 if inside else 1)
        self.canvas.configure(cursor="hand2" if inside else "arrow")

    # ------------------------------------------------------------------ переворот постера
    def _clicked(self, movie_id, event=None):
        """Нажатие на плитку: на кнопку «Выбрать сеанс» — открыть фильм, иначе перевернуть постер."""
        if movie_id in self._flipped and self._on_go_button(movie_id, event):
            self._open(movie_id)
        else:
            self.flip(movie_id)

    def _on_go_button(self, movie_id, event) -> bool:
        x, y, _ = self._tiles[movie_id]
        if event is None or getattr(event, "y", None) is None:
            return False
        point_y = self.canvas.canvasy(event.y)
        return y + TILE_H - 52 <= point_y <= y + TILE_H - 12

    def flip(self, movie_id):
        """Переворачивает плитку: сторона меняется сразу, а рамка плавно «поворачивается» (сужается и расширяется)."""
        if movie_id not in self._tiles or movie_id in self._busy:
            return
        self._flipped ^= {movie_id}
        x, y, frame = self._tiles[movie_id]
        self.canvas.delete(f"face{movie_id}")      # во время поворота содержимого нет, видна только рамка
        self._busy.add(movie_id)
        self._spin(movie_id, 0, self._generation)

    def _spin(self, movie_id, step, generation):
        if generation != self._generation or movie_id not in self._tiles:
            return                                   # афишу перерисовали — старая анимация не нужна
        x, y, frame = self._tiles[movie_id]
        if step > 2 * FLIP_STEPS:
            self._busy.discard(movie_id)
            self._draw_face(movie_id)
            return
        phase = step / FLIP_STEPS                    # 0..1 — сужение, 1..2 — расширение
        scale = max(0.04, abs(1 - phase))
        half = TILE_W / 2 * scale
        centre = x + TILE_W / 2
        self.canvas.coords(frame, *P.rounded_points(centre - half, y, centre + half, y + TILE_H, 14))
        self.after(FLIP_DELAY, lambda: self._spin(movie_id, step + 1, generation))

    def _open(self, movie_id):
        from services.validators import parse_date
        if self.on_open:
            self.on_open(movie_id, parse_date(self.date_var.get()).isoformat())

    # ------------------------------------------------------------------ прокрутка колёсиком
    def _bind_wheel(self, event=None):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(sequence, self._on_wheel)

    def _unbind_wheel(self, event=None):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(sequence)

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:   # Windows: шаги по 120, macOS: небольшие числа
            units = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(units, "units")
