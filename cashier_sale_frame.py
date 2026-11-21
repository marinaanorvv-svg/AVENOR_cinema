"""Продажа билетов на кассе: фильм -> день -> сеанс -> схема зала -> оплата -> билет.

Отдельный экран кассира: афиша и страница фильма (их используют администратор и покупатель) не затронуты.
Вся логика — в cashier_service / ticket_service: здесь только интерфейс.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from services import cashier_service, clock, movie_service, ticket_service

from . import neon
from . import palette as P
from . import theme
from .cashier_dialogs import PaymentDialog, TicketDialog
from .common import guarded
from .film_frame import ClientSearchDialog, SessionCard
from .formatting import (bind_format, format_phone_input, client_payload, day_caption, end_caption, format_duration, format_price, seats_caption,
                         selection_summary)
from .seat_map import SeatMap
from .widgets import Combo

DESC_LIMIT = 110
POLL_MS = 15_000       # схема сама обновляется: так кассир видит места, проданные с другого рабочего места


class CashierSaleFrame(tk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent, bg=P.PANEL)
        self.user = user
        self.navigate = None
        self.error_var, self.selection_var, self.info_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.seat_var, self.total_var, self.day_var, self.shift_var = (tk.StringVar() for _ in range(4))
        self.name_var, self.phone_var = tk.StringVar(), tk.StringVar()
        bind_format(self.phone_var, format_phone_input)
        self._movies = {}
        self._movie_id = self._day = self._session_id = None
        self._days = {}
        self._seat_data, self._selected, self._picked = None, set(), None
        self._thumb = self._job = None
        self._build_ui()
        self.reload_movies()
        self._schedule()

    # ------------------------------------------------------------------ интерфейс
    def _label(self, parent, font_key="body", color=P.TEXT, bg=P.PANEL, **options):
        return tk.Label(parent, font=theme.font(font_key), fg=color, bg=bg, **options)

    def _build_ui(self):
        head = tk.Frame(self, bg=P.PANEL)
        head.pack(fill="x")
        self._label(head, "title", text="Продажа билетов").pack(side="left")
        self.open_shift_button = neon.NeonButton(head, "Открыть смену", self._open_shift, style="ghost", height=36, bg=P.PANEL)
        self._label(head, "small", P.ACCENT_SOFT, textvariable=self.shift_var).pack(side="right", padx=(0, 10))

        body = tk.Frame(self, bg=P.PANEL)
        body.pack(fill="both", expand=True, pady=(8, 0))
        right = neon.RoundedPanel(body, fill=P.PANEL_ALT, bg=P.PANEL, pad=12, glow=False)
        right.configure(width=236)
        right.pack(side="right", fill="y", padx=(12, 0))
        self._build_order_panel(right.body)
        left = neon.RoundedPanel(body, fill=P.PANEL_ALT, bg=P.PANEL, pad=10, glow=False)
        left.configure(width=236)
        left.pack(side="left", fill="y", padx=(0, 12))
        self._build_left(left.body)
        center = tk.Frame(body, bg=P.PANEL)
        center.pack(side="left", fill="both", expand=True)
        self._label(center, "small", P.ACCENT_SOFT, textvariable=self.info_var, anchor="w").pack(side="top", fill="x")
        self._label(center, "bold", P.TEXT, textvariable=self.seat_var, anchor="w").pack(side="top", fill="x", pady=(0, 4))
        self.seat_map = SeatMap(center, on_click=self._on_seat_click)
        self.seat_map.pack(side="top", fill="both", expand=True)

    def _build_left(self, box):
        alt = P.PANEL_ALT
        self._label(box, "small", P.MUTED, alt, text="Фильм в продаже").pack(anchor="w")
        self.movie_combo = Combo(box, [], width=30, on_change=self._on_movie_chosen)
        self.movie_combo.pack(anchor="w", pady=(2, 6))
        top = tk.Frame(box, bg=alt)
        top.pack(fill="x")
        self.poster = tk.Canvas(top, width=76, height=106, bg=alt, bd=0, highlightthickness=0)
        self.poster.pack(side="left")
        self.meta_label = self._label(top, "small", P.MUTED, alt, wraplength=110, justify="left", anchor="nw")
        self.meta_label.pack(side="left", fill="x", padx=(10, 0))
        self.desc_label = self._label(box, "small", P.TEXT, alt, wraplength=204, justify="left", anchor="nw")
        self.desc_label.pack(fill="x", pady=(6, 6))
        nav = tk.Frame(box, bg=alt)
        nav.pack(fill="x", pady=(0, 6))
        neon.NeonButton(nav, "◀", lambda: self._shift_day(-1), style="ghost", height=36, width=30, bg=alt).pack(side="left")
        self._label(nav, "bold", bg=alt, textvariable=self.day_var).pack(side="left", expand=True)
        neon.NeonButton(nav, "▶", lambda: self._shift_day(1), style="ghost", height=36, width=30, bg=alt).pack(side="right")
        self.times_row = tk.Frame(box, bg=alt)
        self.times_row.pack(fill="x")

    def _build_order_panel(self, box):
        alt = P.PANEL_ALT
        # нижняя часть упаковывается первой: кнопка «К оплате» всегда на виду
        self.pay_button = neon.NeonButton(box, "К оплате", self._to_payment, style="primary", width=190, bg=alt)
        self.pay_button.pack(side="bottom", anchor="w", pady=(6, 0))
        self._label(box, "small", P.ERROR, alt, textvariable=self.error_var, wraplength=204, justify="left",
                    anchor="nw").pack(side="bottom", fill="x")
        self._label(box, "h2", bg=alt, textvariable=self.total_var, anchor="w").pack(side="bottom", fill="x")
        self._label(box, "h2", bg=alt, text="Заказ").pack(side="top", anchor="w")
        self._label(box, "small", P.ACCENT_SOFT, alt, textvariable=self.selection_var, wraplength=204, justify="left",
                    anchor="nw", height=4).pack(side="top", fill="x", pady=(4, 6))
        self._label(box, "small", P.MUTED, alt, text="Покупатель (необязательно)").pack(anchor="w")
        for caption, var in (("ФИО", self.name_var), ("Телефон", self.phone_var)):
            self._label(box, "small", P.MUTED, alt, text=caption).pack(anchor="w", pady=(4, 0))
            neon.NeonEntry(box, var, width=190, height=34, bg=alt).pack(anchor="w")
        neon.NeonButton(box, "Найти клиента…", self._pick_client, style="ghost", height=34, width=190,
                        bg=alt).pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------------ смена
    def _refresh_shift(self):
        ok, shift = guarded(self, cashier_service.current_shift, self.user)
        if not ok:
            return None
        if shift:
            self.shift_var.set(f"Смена № {shift['id']} открыта с {shift['opened_at'][11:16]}")
            self.open_shift_button.pack_forget()
        else:
            self.shift_var.set("Смена не открыта")
            self.open_shift_button.pack(side="right", padx=(0, 10))
        return shift

    def _open_shift(self):
        ok, _ = guarded(self, cashier_service.open_shift, self.user)
        if ok:
            self.error_var.set("")
            self._refresh_shift()

    # ------------------------------------------------------------------ фильмы и сеансы
    def reload_movies(self, keep=True):
        self._refresh_shift()
        ok, movies = guarded(self, cashier_service.list_sellable_movies, self.user)
        if not ok:
            return
        self._movies = {m["id"]: m for m in movies}
        previous = self._movie_id if keep else None
        self.movie_combo.set_options([(m["id"], m["title"]) for m in movies], keep_value=False)
        if not movies:
            self._movie_id = None
            self._show_movie(None)
            self._reset_map("Нет фильмов, доступных для продажи.")
            self.day_var.set("Нет сеансов")
            return
        self._movie_id = previous if previous in self._movies else movies[0]["id"]
        self.movie_combo.set_value(self._movie_id)
        self._load_movie()

    def _on_movie_chosen(self):
        value = self.movie_combo.value()
        if value is not None and value != self._movie_id:
            self._movie_id = value
            self._clear_client()
            self._load_movie()

    def _load_movie(self, day=None, reselect=None):
        self._show_movie(self._movies.get(self._movie_id))
        ok, days = guarded(self, cashier_service.list_movie_days, self.user, self._movie_id)
        if not ok:
            return
        self._days = days
        if not days:
            self._day = self._session_id = None
            self.day_var.set("Нет сеансов")
            self._render_times()
            self._reset_map("На этот фильм нет сеансов в продаже.")
            return
        self._select_day(day if day in days else next(iter(days)), reselect)

    def _show_movie(self, movie):
        self.poster.delete("all")
        self._thumb = None
        if movie is None:
            self.meta_label.configure(text="")
            self.desc_label.configure(text="")
            return
        self._thumb = neon.poster_thumb(movie_service.poster_file(movie["poster_path"]), movie["id"])
        if self._thumb is not None:
            self.poster.create_image(0, 0, image=self._thumb, anchor="nw")
        self.meta_label.configure(text=f"{movie['age_rating']}\n{movie['genre_name']}\n{format_duration(movie['duration'])}")
        text = (movie["description"] or "Описание не указано.").strip()
        self.desc_label.configure(text=text if len(text) <= DESC_LIMIT else text[:DESC_LIMIT].rstrip() + "…")

    def _shift_day(self, step):
        days = list(self._days)
        if self._day in days:
            self._select_day(days[(days.index(self._day) + step) % len(days)])

    def _select_day(self, day, reselect=None):
        self._day = day
        sessions = self._days[day]
        self.day_var.set(day_caption(day, clock.now().date()))
        free = next((s for s in sessions if s["seats_free"] > 0), sessions[0])
        self._open_session(reselect if reselect in {s["id"] for s in sessions} else free["id"])

    def _render_times(self):
        for child in self.times_row.winfo_children():
            child.destroy()
        for session in self._days.get(self._day, ()):
            SessionCard(self.times_row, session, session["id"] == self._session_id, self._open_session).pack(pady=(0, 6))

    # ------------------------------------------------------------------ схема мест
    def _reset_map(self, message=""):
        self._seat_data, self._selected = None, set()
        self.info_var.set(message)
        self.seat_var.set("")
        self.selection_var.set("")
        self.total_var.set("")
        self.seat_map.render([])
        self.pay_button.set_enabled(False)

    def _open_session(self, session_id, keep=None):
        self._session_id = session_id
        self._render_times()
        ok, data = guarded(self, ticket_service.get_session_seat_map, self.user, session_id)
        if not ok:
            self._reset_map()
            return
        self._seat_data = data
        free = {s["id"] for row in data["rows"] for s in row["seats"] if not s["is_sold"]}
        self._selected = set(keep or ()) & free
        s = next((x for x in self._days.get(self._day, ()) if x["id"] == session_id), data["session"])
        self.info_var.set(f"{s['hall_name']} · {end_caption(s)} · билет {format_price(s['price'])}")
        self.error_var.set("" if data["is_open_for_sale"] else "Сеанс уже начался — продажа закрыта.")
        self.seat_var.set("")
        self._redraw()

    def _redraw(self):
        data = self._seat_data
        self.seat_map.render(data["rows"], self._selected)
        price = data["session"]["price"]
        labels, total = selection_summary(data["rows"], self._selected, price)
        vip = sum(1 for row in data["rows"] for s in row["seats"] if s["id"] in self._selected and s["seat_type"] == "vip")
        if labels:
            self.selection_var.set(f"{seats_caption(data['rows'], self._selected)}\nБилетов: {len(labels)}"
                                   + (f", из них VIP: {vip}" if vip else ""))
        else:
            self.selection_var.set("Нажмите на свободные кресла." if data["is_open_for_sale"] else "")
        self.total_var.set(f"Итого {format_price(total)}" if labels else "")
        self.pay_button.set_enabled(bool(labels) and data["is_open_for_sale"])

    def _on_seat_click(self, seat):
        data = self._seat_data
        if data is None or not data["is_open_for_sale"] or seat["is_sold"]:
            return
        row = next(r for r in data["rows"] if any(s["id"] == seat["id"] for s in r["seats"]))
        category = "VIP" if seat["seat_type"] == "vip" else "Обычное"
        self.seat_var.set(f"Ряд {row['row_number']} · место {seat['seat_number']} · {category} · "
                          f"{format_price(data['session']['price'])}")
        if seat["id"] in self._selected:
            self._selected.discard(seat["id"])
        elif len(self._selected) >= ticket_service.MAX_SEATS_PER_PURCHASE:
            self.error_var.set(f"За одну продажу — не более {ticket_service.MAX_SEATS_PER_PURCHASE} мест.")
            return
        else:
            self._selected.add(seat["id"])
        self.error_var.set("")
        self._redraw()

    # ------------------------------------------------------------------ клиент
    def _pick_client(self):
        ClientSearchDialog(self, self.user, self._on_client_picked)

    def _on_client_picked(self, client):
        self._picked = client
        self.name_var.set(client["full_name"])
        self.phone_var.set(client["phone"] or "")

    def _clear_client(self):
        self._picked = None
        self.name_var.set("")
        self.phone_var.set("")

    # ------------------------------------------------------------------ оплата
    def _seat_order(self):
        data = self._seat_data
        return [s["id"] for row in data["rows"] for s in row["seats"] if s["id"] in self._selected]

    def _to_payment(self):
        if self._seat_data is None or not self._selected:
            self.error_var.set("Выберите кресла на схеме.")
            return
        if self._refresh_shift() is None:
            self.error_var.set("Смена не открыта: нажмите «Открыть смену».")
            return
        session_id, seat_ids = self._session_id, self._seat_order()
        ok, quote = guarded(self, cashier_service.quote, self.user, session_id, seat_ids)   # актуальная доступность
        if not ok:
            return
        if quote["unavailable"]:
            labels = self._labels_of(quote["unavailable"])
            self._open_session(session_id, keep=set(seat_ids))
            self.error_var.set(f"Место уже продано: {labels}. Схема обновлена.")
            messagebox.showwarning("Место недоступно", f"Эти места уже проданы: {labels}.\n"
                                   "Схема обновлена — выберите другие места.", parent=self)
            return
        if not quote["open"] or not quote["count"]:
            self.error_var.set("Продажа на этот сеанс закрыта.")
            return
        PaymentDialog(self, quote, lambda method: self._confirm_payment(method, session_id, seat_ids))

    def _labels_of(self, seat_ids):
        wanted = set(seat_ids)
        return "; ".join(f"ряд {row['row_number']}, место {s['seat_number']}"
                         for row in self._seat_data["rows"] for s in row["seats"] if s["id"] in wanted)

    def _confirm_payment(self, method, session_id, seat_ids):
        client = client_payload(self._picked, self.name_var.get(), self.phone_var.get(), "")
        ok, result = guarded(self, cashier_service.sell, self.user, session_id, seat_ids, method, client)
        if not ok:      # например, место успели продать: обновляем схему, свободные выбранные оставляем
            self._open_session(session_id, keep=set(seat_ids))
            return False
        self._clear_client()
        self._load_movie(self._day, reselect=session_id)
        messagebox.showinfo("Продажа оформлена", f"Продажа № {result['sale_id']} оформлена.\n"
                            f"Билетов: {len(result['tickets'])}, сумма: {format_price(result['total'])}.", parent=self)
        TicketDialog(self, result["tickets"])
        return True

    # ------------------------------------------------------------------ автообновление схемы
    def _schedule(self):
        self._job = self.after(POLL_MS, self._poll)

    def _poll(self):
        self._job = None
        if self._seat_data is not None and self._session_id is not None:
            before = set(self._selected)
            ok, data = guarded(self, ticket_service.get_session_seat_map, self.user, self._session_id)
            if ok:
                self._seat_data = data
                free = {s["id"] for row in data["rows"] for s in row["seats"] if not s["is_sold"]}
                lost = before - free
                self._selected = before & free
                if lost:
                    self.error_var.set(f"Место уже продано: {self._labels_of(lost)}.")
                self._redraw()
        self._schedule()

    def destroy(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        super().destroy()
