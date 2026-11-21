"""Страница фильма: только выбранный фильм, его сеансы, кресла в зале и покупка билетов.

Покупатель оформляет билеты на себя, кассир и администратор — на клиента.
"""
import tkinter as tk
from datetime import timedelta
from tkinter import messagebox, ttk

from services import client_service, movie_service, session_service, ticket_service
from services.errors import ServiceError
from services.permissions import Permission

from . import neon
from . import palette as P
from . import theme
from .common import center_on_parent, guarded
from .formatting import (bind_format, format_phone_input, client_payload, date_ru_from_iso, day_caption, end_caption, format_duration, format_price,
                         receipt_text, seats_caption, selection_summary)
from .seat_map import SeatMap
from .widgets import DataTable
from services import clock

MAX_DAYS = 7          # на сколько ближайших дней с сеансами можно листать стрелками
DESC_LIMIT = 220


class ClientSearchDialog(tk.Toplevel):
    """Поиск существующего клиента по ФИО, email или части телефона."""
    COLUMNS = (("name", "ФИО", 210), ("phone", "Телефон", 130), ("email", "Email", 190))

    def __init__(self, parent, user, on_pick):
        super().__init__(parent)
        self.user, self.on_pick = user, on_pick
        self._clients = {}
        self.query_var = tk.StringVar()
        self.title("Поиск клиента")
        self.transient(parent.winfo_toplevel())
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        entry = ttk.Entry(top, textvariable=self.query_var, width=32)
        entry.pack(side="left")
        entry.bind("<Return>", lambda event: self.search())
        ttk.Button(top, text="Найти", command=self.search).pack(side="left", padx=6)
        self.table = DataTable(self, self.COLUMNS, height=10, on_activate=self._choose)
        self.table.pack(fill="both", expand=True, padx=12)
        bottom = ttk.Frame(self, padding=12)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Выбрать", command=self._choose).pack(side="left")
        ttk.Button(bottom, text="Закрыть", command=self.destroy).pack(side="left", padx=6)
        center_on_parent(self, parent, 620, 420)
        self.wait_visibility()
        self.grab_set()
        entry.focus_set()
        self.search()

    def search(self):
        ok, clients = guarded(self, client_service.search_clients, self.user, self.query_var.get())
        if ok:
            self._clients = {c["id"]: c for c in clients}
            self.table.set_rows((c["id"], (c["full_name"], c["phone"] or "", c["email"] or ""), None)
                                for c in clients)

    def _choose(self):
        iid = self.table.selected_id()
        if iid is None:
            return
        client = self._clients[int(iid)]
        self.destroy()
        self.on_pick(client)


class SessionCard(tk.Canvas):
    """Карточка сеанса в списке слева: время, зал, конец сеанса и цена. Выбранная подсвечена."""
    W, H = 206, 66

    def __init__(self, parent, session, selected, on_click):
        super().__init__(parent, width=self.W, height=self.H, bg=P.PANEL_ALT, bd=0, highlightthickness=0, cursor="hand2")
        self.session, self.selected, self.on_click, self.hovered = session, selected, on_click, False
        self.bind("<Button-1>", lambda event: self.on_click(self.session["id"]))
        self.bind("<Enter>", lambda event: self._hover(True))
        self.bind("<Leave>", lambda event: self._hover(False))
        self._draw()

    def _hover(self, value):
        self.hovered = value
        self._draw()

    def _draw(self):
        s = self.session
        self.delete("all")
        fill = P.VIOLET if self.selected else P.PANEL
        outline = P.ACCENT if (self.selected or self.hovered) else P.LINE
        self.create_polygon(P.rounded_points(2, 2, self.W - 2, self.H - 2, 14), smooth=True, fill=fill,
                            outline=outline, width=2 if self.selected or self.hovered else 1)
        self.create_text(14, 10, text=s["session_time"], anchor="nw", fill="#ffffff", font=theme.font("bold"))
        self.create_text(14, 30, text=f"{s['hall_name']} · {end_caption(s)}", anchor="nw", fill=P.TEXT,
                         font=theme.font("small"))
        free = "нет мест" if s["seats_free"] <= 0 else f"свободно {s['seats_free']}"
        self.create_text(14, 46, text=f"{format_price(s['price'])} · {free}", anchor="nw",
                         fill=P.ACCENT_SOFT if not self.selected else "#ffffff", font=theme.font("small"))
        self.create_text(self.W - 16, self.H // 2, text="›", fill=P.MUTED if not self.selected else "#ffffff",
                         font=theme.font("h2"))


class FilmFrame(tk.Frame):
    """Один фильм: день -> время -> кресла -> «Купить». Других фильмов на экране нет.

    Три колонки, как на макете: слева фильм и его сеансы, в центре зал, справа покупатель, итог и кнопка.
    """

    def __init__(self, parent, user, movie_id, date_iso=None, on_back=None):
        super().__init__(parent, bg=P.PANEL)
        self.user, self.movie_id, self.on_back = user, movie_id, on_back
        self.self_service = not user.has_permission(Permission.SELL_TICKET)   # покупатель оформляет билеты на себя
        self.can_buy = not self.self_service or user.client_id is not None
        self.error_var, self.selection_var, self.info_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.total_var, self.day_var = tk.StringVar(), tk.StringVar()
        self.name_var, self.phone_var, self.email_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        bind_format(self.phone_var, format_phone_input)      # +7 916 903-56-00 — пробелы и дефисы ставятся сами
        self._movie = None
        self._days = {}            # дата ISO -> сеансы, на которые ещё можно купить билет
        self._day = self._session_id = None
        self._seat_data = None     # ответ get_session_seat_map для открытого сеанса
        self._selected = set()     # id выбранных мест
        self._picked = None        # клиент, найденный через поиск
        self._thumb = None
        self._build_ui()
        self.load(date_iso)

    # ------------------------------------------------------------------ интерфейс
    def _label(self, parent, font_key="body", color=P.TEXT, bg=P.PANEL, **options):
        return tk.Label(parent, font=theme.font(font_key), fg=color, bg=bg, **options)

    def _build_ui(self):
        head = tk.Frame(self, bg=P.PANEL)
        head.pack(fill="x")
        self.back_button = neon.NeonButton(head, "← Афиша", self._back, style="ghost", height=36, bg=P.PANEL)
        self.back_button.pack(side="left")
        self.title_label = self._label(head, "title", text="")
        self.title_label.pack(side="left", padx=(14, 0))

        body = tk.Frame(self, bg=P.PANEL)
        body.pack(fill="both", expand=True, pady=(8, 0))
        # правая колонка упаковывается первой: кнопка «Купить» никогда не окажется за краем окна
        right = neon.RoundedPanel(body, fill=P.PANEL_ALT, bg=P.PANEL, pad=12, glow=False)
        right.configure(width=236)
        right.pack(side="right", fill="y", padx=(12, 0))
        self._build_buyer_panel(right.body)
        left = neon.RoundedPanel(body, fill=P.PANEL_ALT, bg=P.PANEL, pad=10, glow=False)
        left.configure(width=236)
        left.pack(side="left", fill="y", padx=(0, 12))
        self._build_left(left.body)
        center = tk.Frame(body, bg=P.PANEL)
        center.pack(side="left", fill="both", expand=True)
        self._label(center, "small", P.ACCENT_SOFT, textvariable=self.info_var, anchor="w").pack(side="top", fill="x", pady=(0, 4))
        self.seat_map = SeatMap(center, on_click=self._on_seat_click)
        self.seat_map.pack(side="top", fill="both", expand=True)

    def _build_left(self, box):
        alt = P.PANEL_ALT
        top = tk.Frame(box, bg=alt)
        top.pack(fill="x")
        self.poster = tk.Canvas(top, width=76, height=106, bg=alt, bd=0, highlightthickness=0)
        self.poster.pack(side="left")
        info = tk.Frame(top, bg=alt)
        info.pack(side="left", fill="x", padx=(10, 0))
        self.meta_label = self._label(info, "small", P.MUTED, alt, wraplength=110, justify="left", anchor="nw")
        self.meta_label.pack(fill="x")
        self.desc_label = self._label(box, "small", P.TEXT, alt, wraplength=204, justify="left", anchor="nw")
        self.desc_label.pack(fill="x", pady=(6, 6))
        nav = tk.Frame(box, bg=alt)
        nav.pack(fill="x", pady=(0, 6))
        neon.NeonButton(nav, "◀", lambda: self._shift_day(-1), style="ghost", height=36, width=30, bg=alt).pack(side="left")
        self.days_row = nav     # здесь же подпись выбранного дня
        self._label(nav, "bold", bg=alt, textvariable=self.day_var).pack(side="left", expand=True)
        neon.NeonButton(nav, "▶", lambda: self._shift_day(1), style="ghost", height=36, width=30, bg=alt).pack(side="right")
        self.times_row = tk.Frame(box, bg=alt)
        self.times_row.pack(fill="x")

    def _build_buyer_panel(self, box):
        alt = P.PANEL_ALT
        # Сначала упаковывается нижняя часть (кнопка, ошибка, итог, места): если окно низкое, обрежутся
        # поля клиента, а кнопка «Купить» останется на виду.
        self.buy_button = neon.NeonButton(box, "Купить билеты" if self.self_service else "Оформить билеты",
                                          self._buy, style="primary", width=190, bg=alt)
        self.buy_button.pack(side="bottom", anchor="w", pady=(6, 0))
        self._label(box, "small", P.ERROR, alt, textvariable=self.error_var, wraplength=204, justify="left",
                    anchor="nw").pack(side="bottom", fill="x")
        self._label(box, "h2", bg=alt, textvariable=self.total_var, anchor="w").pack(side="bottom", fill="x")
        self._label(box, "small", P.ACCENT_SOFT, alt, textvariable=self.selection_var, wraplength=204,
                    justify="left", anchor="nw", height=2).pack(side="bottom", fill="x", pady=(8, 0))
        self._label(box, "h2", bg=alt, text="Покупатель" if self.self_service else "Клиент").pack(side="top", anchor="w")
        if self.self_service:
            self._label(box, "bold", bg=alt, text=self.user.full_name, wraplength=200, justify="left").pack(anchor="w", pady=(6, 4))
        else:
            for caption, var in (("ФИО *", self.name_var), ("Телефон", self.phone_var), ("Email", self.email_var)):
                self._label(box, "small", P.MUTED, alt, text=caption).pack(anchor="w", pady=(6, 0))
                neon.NeonEntry(box, var, width=190, height=36, bg=alt).pack(anchor="w")
            neon.NeonButton(box, "Найти клиента…", self._pick_client, style="ghost", height=36, width=190,
                            bg=alt).pack(anchor="w", pady=(6, 0))
        deco = tk.Canvas(box, height=20, bg=alt, bd=0, highlightthickness=0)
        deco.pack(side="top", fill="both", expand=True)
        deco.bind("<Configure>", lambda event: self._draw_deco(deco, event.width, event.height))

    def _draw_deco(self, canvas, width, height):
        """Низ правой панели: звёзды и пожелание."""
        canvas.delete("all")
        neon.draw_stars(canvas, width, height, 14)
        if height >= 40:                       # в низком окне пожелание не показываем: нужно место под кнопку
            canvas.create_text(width // 2, height // 2, text="Приятного просмотра!", fill=P.ACCENT_SOFT,
                               font=theme.font("bold"))

    # ------------------------------------------------------------------ данные
    def load(self, date_iso=None, reselect=None):
        """Загружает фильм и сеансы на ближайшие дни (только те, что ещё не начались)."""
        ok, movie = guarded(self, movie_service.get_movie, self.user, self.movie_id)
        if not ok:
            return
        self._movie = movie
        today = clock.now().date()
        ok, sessions = guarded(self, session_service.list_sessions, self.user, date_from=today.isoformat(),
                               date_to=(today + timedelta(days=30)).isoformat(), movie_id=self.movie_id)
        if not ok:
            return
        self._days = {}
        for s in sessions:
            if not s["started"]:
                self._days.setdefault(s["session_date"], []).append(s)
        self._days = dict(list(self._days.items())[:MAX_DAYS])
        self._show_movie()
        if not self._days:
            self._day = self._session_id = None
            self._render_days()
            self._reset_map("На этот фильм пока нет сеансов.")
            return
        self._day = date_iso if date_iso in self._days else next(iter(self._days))
        self._render_days()
        self._select_day(self._day, reselect)

    def _show_movie(self):
        movie = self._movie
        self.title_label.configure(text=movie["title"])
        self.poster.delete("all")
        thumb = neon.poster_thumb(movie_service.poster_file(movie["poster_path"]), movie["id"])   # постер вдвое меньше
        self._thumb = thumb
        if thumb is not None:
            self.poster.create_image(0, 0, image=thumb, anchor="nw")
        self.meta_label.configure(text=f"{movie['age_rating']}\n{movie['genre_name']}\n{format_duration(movie['duration'])}")
        text = (movie["description"] or "Описание не указано.").strip()
        self.desc_label.configure(text=text if len(text) <= DESC_LIMIT else text[:DESC_LIMIT].rstrip() + "…")

    def _back(self):
        if self.on_back:
            self.on_back()

    # ------------------------------------------------------------------ день и время
    def _render_days(self):
        """Подпись выбранного дня между стрелками: «Сегодня», «Завтра» или «30.10 пт»."""
        self.day_var.set(day_caption(self._day, clock.now().date()) if self._day else "Нет сеансов")

    def _shift_day(self, step):
        """Стрелки ◀ ▶ листают дни, на которые у фильма есть сеансы."""
        days = list(self._days)
        if self._day in days:
            self._select_day(days[(days.index(self._day) + step) % len(days)])

    def _render_times(self):
        for child in self.times_row.winfo_children():
            child.destroy()
        for session in self._days.get(self._day, ()):
            SessionCard(self.times_row, session, session["id"] == self._session_id,
                        self._open_session).pack(pady=(0, 6))

    def _select_day(self, day, reselect=None):
        self._day = day
        sessions = self._days[day]
        free = next((s for s in sessions if s["seats_free"] > 0), sessions[0])
        self._render_days()
        self._open_session(reselect if reselect in {s["id"] for s in sessions} else free["id"])

    def _session(self, session_id):
        return next((s for s in self._days.get(self._day, ()) if s["id"] == session_id), None)

    # ------------------------------------------------------------------ схема мест
    def _reset_map(self, message=""):
        self._seat_data, self._selected = None, set()
        self.info_var.set(message)
        self.selection_var.set("")
        self.total_var.set("")
        self.seat_map.render([])
        self.buy_button.set_enabled(False)

    def _open_session(self, session_id):
        self._session_id = session_id
        self._render_times()
        ok, data = guarded(self, ticket_service.get_session_seat_map, self.user, session_id)
        if not ok:
            self._reset_map()
            return
        self._seat_data, self._selected = data, set()
        s = self._session(session_id) or data["session"]
        self.info_var.set(f"{s['hall_name']} · {end_caption(s)} · билет {format_price(s['price'])}")
        self.error_var.set("")
        if not data["is_open_for_sale"]:
            self.error_var.set("Сеанс уже начался — продажа закрыта.")
        self._redraw()

    def _redraw(self):
        data = self._seat_data
        self.seat_map.render(data["rows"], self._selected)
        labels, total = selection_summary(data["rows"], self._selected, data["session"]["price"])
        self.selection_var.set(seats_caption(data["rows"], self._selected) if labels else
                               ("Нажмите на свободные кресла." if data["is_open_for_sale"] else ""))
        self.total_var.set(f"Итого {format_price(total)}" if labels else "")
        self.buy_button.set_enabled(bool(labels) and data["is_open_for_sale"] and self.can_buy)

    def _on_seat_click(self, seat):
        data = self._seat_data
        if data is None or not data["is_open_for_sale"] or seat["is_sold"]:
            return
        if not self.can_buy:
            self.error_var.set("Эта учётная запись не привязана к покупателю — купить билет нельзя.")
            return
        if seat["id"] in self._selected:
            self._selected.discard(seat["id"])
        elif len(self._selected) >= ticket_service.MAX_SEATS_PER_PURCHASE:
            self.error_var.set(f"За одну покупку — не более {ticket_service.MAX_SEATS_PER_PURCHASE} мест.")
            return
        else:
            self._selected.add(seat["id"])
        self.error_var.set("")
        self._redraw()

    # ------------------------------------------------------------------ клиент и покупка
    def _pick_client(self):
        ClientSearchDialog(self, self.user, self._on_client_picked)

    def _on_client_picked(self, client):
        self._picked = client
        self.name_var.set(client["full_name"])
        self.phone_var.set(client["phone"] or "")
        self.email_var.set(client["email"] or "")

    def _clear_client(self):
        self._picked = None
        for var in (self.name_var, self.phone_var, self.email_var):
            var.set("")

    def _buy(self):
        data = self._seat_data
        if data is None or not self._selected:
            self.error_var.set("Выберите кресла на схеме.")
            return
        seat_ids = [seat["id"] for row in data["rows"] for seat in row["seats"] if seat["id"] in self._selected]
        if self.self_service:
            payload = self.user.client_id
        else:
            payload = client_payload(self._picked, self.name_var.get(), self.phone_var.get(), self.email_var.get())
        session_id = self._session_id
        ok, tickets = guarded(self, ticket_service.sell_tickets, self.user, session_id, seat_ids, payload)
        if not ok:
            # Например, место успел купить другой человек: обновляем схему, свободные выбранные места оставляем.
            previous = set(self._selected)
            self._open_session(session_id)
            if self._seat_data is not None:
                free = {s["id"] for row in self._seat_data["rows"] for s in row["seats"] if not s["is_sold"]}
                self._selected = previous & free
                self._redraw()
            return
        messagebox.showinfo("Билеты оформлены", receipt_text(tickets), parent=self)
        self._clear_client()
        self.load(self._day, reselect=session_id)
