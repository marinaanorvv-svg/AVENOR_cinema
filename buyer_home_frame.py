"""Главная страница покупателя: логотип, приветствие, ближайший билет, афиша, популярное и новинки."""
import tkinter as tk

from services import buyer_service

from . import neon
from . import palette as P
from . import theme
from .buyer_widgets import DayBar, MovieWall
from .common import guarded
from .formatting import date_ru_from_iso


class BuyerHomeFrame(tk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent, bg=P.PANEL)
        self.user = user
        self.navigate = None      # MainFrame: open_screen(key)
        self.open_movie = None    # MainFrame: открыть страницу фильма
        self.hello_var, self.ticket_var = tk.StringVar(), tk.StringVar()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        head = tk.Frame(self, bg=P.PANEL)
        head.pack(fill="x")
        logo = tk.Canvas(head, width=230, height=52, bg=P.PANEL, bd=0, highlightthickness=0)
        logo.pack(side="left")
        neon.draw_logo(logo, 6, 26)
        texts = tk.Frame(head, bg=P.PANEL)
        texts.pack(side="left", padx=(8, 0))
        tk.Label(texts, textvariable=self.hello_var, font=theme.font("title"), fg=P.TEXT, bg=P.PANEL).pack(anchor="w")
        tk.Label(texts, textvariable=self.ticket_var, font=theme.font("small"), fg=P.ACCENT_SOFT, bg=P.PANEL,
                 justify="left").pack(anchor="w")
        buttons = tk.Frame(head, bg=P.PANEL)
        buttons.pack(side="right")
        neon.NeonButton(buttons, "Мои билеты", lambda: self._go("my_tickets"), style="primary", height=40,
                        bg=P.PANEL).pack(side="left", padx=(0, 8))
        neon.NeonButton(buttons, "Вся афиша", lambda: self._go("poster"), style="ghost", height=40,
                        bg=P.PANEL).pack(side="left")
        self.day_bar = DayBar(self, self._pick_day)
        self.day_bar.pack(fill="x", pady=(8, 0))
        self.wall = MovieWall(self, self._open)
        self.wall.pack(fill="both", expand=True, pady=(8, 0))

    def _go(self, key):
        if self.navigate:
            self.navigate(key)

    def _pick_day(self, day):
        """Нажали «Сегодня», «Завтра» и т. д.: открываем афишу сразу на этот день."""
        if self.navigate and day:
            self.navigate("poster", day=day)
        elif self.navigate:
            self.navigate("poster")

    def _open(self, movie_id):
        if self.open_movie:
            self.open_movie(movie_id)

    def refresh(self):
        ok, data = guarded(self, buyer_service.home, self.user)
        if not ok:
            return
        ok_days, days = guarded(self, buyer_service.catalog_days, self.user)
        self.day_bar.set_days(days if ok_days else [])
        self.hello_var.set(f"Добро пожаловать, {data['name']}!")
        nxt = data["next_ticket"]
        if nxt:
            self.ticket_var.set(f"Ближайший сеанс: «{nxt['movie_title']}», {date_ru_from_iso(nxt['session_date'])[:5]} "
                                f"в {nxt['session_time']}, {nxt['seat_label']}. Билетов впереди: {data['upcoming_tickets']}")
        else:
            self.ticket_var.set("У вас пока нет предстоящих сеансов — выберите фильм в афише.")
        self.wall.set_sections([("Сейчас в афише", data["now_showing"]), ("Популярное", data["popular"]),
                                ("Новинки", data["new"])],
                               "Сейчас нет доступных фильмов. Загляните позже — афиша обновляется.", max_rows=1)
