"""Афиша покупателя: все фильмы, на которые можно купить билет, с поиском, фильтрами и сортировкой."""
import tkinter as tk

from services import buyer_service

from . import neon
from . import palette as P
from . import theme
from .buyer_widgets import DayBar, MovieWall
from .common import guarded
from .widgets import Combo

ALL = (None, "Все")


class BuyerPosterFrame(tk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent, bg=P.PANEL)
        self.user = user
        self.navigate = None
        self.open_movie = None
        self.search_var, self.info_var = tk.StringVar(), tk.StringVar()
        self._build_ui()
        self._load_filters()
        self.refresh()

    def _label(self, parent, text=None, font_key="small", color=P.MUTED, **options):
        return tk.Label(parent, text=text, font=theme.font(font_key), fg=color, bg=P.PANEL, **options)

    def _build_ui(self):
        head = tk.Frame(self, bg=P.PANEL)
        head.pack(fill="x")
        self._label(head, "Афиша", "title", P.TEXT).pack(side="left")
        self._label(head, textvariable=self.info_var).pack(side="left", padx=14)
        bar = tk.Frame(self, bg=P.PANEL)
        bar.pack(fill="x", pady=(8, 0))
        self.search_entry = neon.NeonEntry(bar, self.search_var, width=220, height=36, bg=P.PANEL)
        self.search_entry.pack(side="left")
        self.search_entry.entry.bind("<Return>", lambda event: self.refresh())
        neon.NeonButton(bar, "Найти", self.refresh, style="ghost", height=36, bg=P.PANEL).pack(side="left", padx=(6, 12))
        self._label(bar, "Жанр:").pack(side="left", padx=(0, 4))
        self.genre_combo = Combo(bar, [ALL], width=14, on_change=self.refresh)
        self.genre_combo.set_value(None)
        self.genre_combo.pack(side="left", padx=(0, 10))
        self._label(bar, "Возраст:").pack(side="left", padx=(0, 4))
        self.age_combo = Combo(bar, [ALL], width=7, on_change=self.refresh)
        self.age_combo.set_value(None)
        self.age_combo.pack(side="left", padx=(0, 10))
        self._label(bar, "Сортировка:").pack(side="left", padx=(0, 4))
        self.sort_combo = Combo(bar, buyer_service.SORTS, width=20, on_change=self.refresh)
        self.sort_combo.set_value("title")
        self.sort_combo.pack(side="left", padx=(0, 10))
        neon.NeonButton(bar, "Сбросить", self.reset, style="ghost", height=36, bg=P.PANEL).pack(side="left")
        self.day_bar = DayBar(self, lambda day: self.refresh())
        self.day_bar.pack(fill="x", pady=(8, 0))
        self.wall = MovieWall(self, self._open)
        self.wall.pack(fill="both", expand=True, pady=(8, 0))

    def set_day(self, day):
        """Переход с главной: сразу показать афишу на выбранный день."""
        self.day_bar.set_days(self.day_bar.days, day)
        self.refresh()

    def _load_filters(self):
        ok, filters = guarded(self, buyer_service.catalog_filters, self.user)
        if ok:
            ok_days, days = guarded(self, buyer_service.catalog_days, self.user)
            self.day_bar.set_days(days if ok_days else [], self.day_bar.selected)
            self.genre_combo.set_options([ALL] + [(g, g) for g in filters["genres"]])
            self.age_combo.set_options([ALL] + [(a, a) for a in filters["ages"]])
            self.genre_combo.set_value(None)
            self.age_combo.set_value(None)

    def refresh(self):
        ok, movies = guarded(self, buyer_service.catalog, self.user, search=self.search_var.get(),
                             genre=self.genre_combo.value(), age=self.age_combo.value(),
                             sort=self.sort_combo.value() or "title", day=self.day_bar.selected)
        if not ok:
            return
        filtered = bool(self.day_bar.selected or self.search_var.get().strip() or self.genre_combo.value() or self.age_combo.value())
        self.info_var.set(f"Найдено фильмов: {len(movies)}")
        self.wall.set_sections([(None, movies)],
                               "По вашему запросу ничего не найдено. Измените поиск или фильтры." if filtered
                               else "Сейчас нет доступных фильмов. Загляните позже — афиша обновляется.")

    def reset(self):
        self.search_var.set("")
        self.genre_combo.set_value(None)
        self.age_combo.set_value(None)
        self.sort_combo.set_value("title")
        self.day_bar.set_days(self.day_bar.days, None)
        self.refresh()

    def _open(self, movie_id):
        if self.open_movie:
            self.open_movie(movie_id)
