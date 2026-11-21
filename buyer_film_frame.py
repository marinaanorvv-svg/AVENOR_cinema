"""Страница фильма покупателя: описание, даты, сеансы, интерактивная схема зала и оформление заказа."""
import tkinter as tk
from tkinter import messagebox

from services import buyer_service, clock, ticket_service

from . import neon
from . import palette as P
from . import theme
from .buyer_dialogs import CheckoutDialog, ETicketDialog
from .common import guarded
from .film_frame import SessionCard
from .formatting import (day_caption, end_caption, format_duration, format_price, seats_caption,
                         selection_summary)
from .seat_map import SeatMap
from services import movie_service

POLL_MS = 15000


class BuyerFilmFrame(tk.Frame):
    def __init__(self, parent, user, movie_id, date_iso=None, on_back=None):
        super().__init__(parent, bg=P.PANEL)
        self.user, self.movie_id, self.on_back = user, movie_id, on_back
        self.error_var, self.selection_var, self.seat_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.info_var, self.total_var, self.day_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self._movie, self._days = None, {}
        self._day = self._session_id = None
        self._seat_data, self._selected = None, set()
        self._thumb, self._job = None, None
        self._build_ui()
        self.load(date_iso)
        self._schedule()

    def _label(self, parent, font_key="body", color=P.TEXT, bg=P.PANEL, **options):
        return tk.Label(parent, font=theme.font(font_key), fg=color, bg=bg, **options)

    # ------------------------------------------------------------------ интерфейс
    def _build_ui(self):
        head = tk.Frame(self, bg=P.PANEL)
        head.pack(fill="x")
        neon.NeonButton(head, "← Афиша", self._back, style="ghost", height=36, bg=P.PANEL).pack(side="left")
        self.title_label = self._label(head, "title", text="")
        self.title_label.pack(side="left", padx=(14, 0))
        banner = tk.Frame(self, bg=P.PANEL)
        banner.pack(fill="x", pady=(8, 0))
        self.poster = tk.Canvas(banner, width=75, height=105, bg=P.PANEL, bd=0, highlightthickness=0)
        self.poster.pack(side="left")
        info = tk.Frame(banner, bg=P.PANEL)
        info.pack(side="left", fill="x", expand=True, padx=(12, 0))
        self.meta_label = self._label(info, "bold", P.ACCENT_SOFT, anchor="w", justify="left")
        self.meta_label.pack(fill="x")
        self.desc_label = self._label(info, "small", P.TEXT, anchor="nw", justify="left", wraplength=620)
        self.desc_label.pack(fill="x", pady=(4, 0))

        body = tk.Frame(self, bg=P.PANEL)
        body.pack(fill="both", expand=True, pady=(8, 0))
        right = neon.RoundedPanel(body, fill=P.PANEL_ALT, bg=P.PANEL, pad=12, glow=False)
        right.configure(width=236)
        right.pack(side="right", fill="y", padx=(12, 0))
        self._build_order_panel(right.body)
        left = neon.RoundedPanel(body, fill=P.PANEL_ALT, bg=P.PANEL, pad=10, glow=False)
        left.configure(width=236)
        left.pack(side="left", fill="y", padx=(0, 12))
        self._build_sessions(left.body)
        center = tk.Frame(body, bg=P.PANEL)
        center.pack(side="left", fill="both", expand=True)
        self._label(center, "small", P.ACCENT_SOFT, textvariable=self.info_var, anchor="w").pack(side="top", fill="x", pady=(0, 4))
        self.seat_map = SeatMap(center, on_click=self._on_seat_click)
        self.seat_map.pack(side="top", fill="both", expand=True)

    def _build_sessions(self, box):
        alt = P.PANEL_ALT
        self._label(box, "h2", bg=alt, text="Дата и время").pack(anchor="w")
        nav = tk.Frame(box, bg=alt)
        nav.pack(fill="x", pady=(6, 6))
        neon.NeonButton(nav, "◀", lambda: self._shift_day(-1), style="ghost", height=36, width=30, bg=alt).pack(side="left")
        self._label(nav, "bold", bg=alt, textvariable=self.day_var).pack(side="left", expand=True)
        neon.NeonButton(nav, "▶", lambda: self._shift_day(1), style="ghost", height=36, width=30, bg=alt).pack(side="right")
        self.times_row = tk.Frame(box, bg=alt)
        self.times_row.pack(fill="x")

    def _build_order_panel(self, box):
        alt = P.PANEL_ALT
        self.buy_button = neon.NeonButton(box, "Оформить заказ", self._to_checkout, style="primary", width=190, bg=alt)
        self.buy_button.pack(side="bottom", anchor="w", pady=(6, 0))
        self._label(box, "small", P.ERROR, alt, textvariable=self.error_var, wraplength=204, justify="left",
                    anchor="nw").pack(side="bottom", fill="x")
        self._label(box, "h2", bg=alt, textvariable=self.total_var, anchor="w").pack(side="bottom", fill="x")
        self._label(box, "small", P.ACCENT_SOFT, alt, textvariable=self.selection_var, wraplength=204,
                    justify="left", anchor="nw", height=3).pack(side="bottom", fill="x", pady=(8, 0))
        self._label(box, "h2", bg=alt, text="Ваш заказ").pack(side="top", anchor="w")
        self._label(box, "bold", bg=alt, text=self.user.full_name, wraplength=200, justify="left").pack(anchor="w", pady=(6, 4))
        self._label(box, "small", P.MUTED, alt, textvariable=self.seat_var, wraplength=204, justify="left",
                    anchor="nw").pack(anchor="w", pady=(6, 0))

    # ------------------------------------------------------------------ данные
    def load(self, date_iso=None, reselect=None):
        ok, page = guarded(self, buyer_service.movie_page, self.user, self.movie_id)
        if not ok:
            return
        self._movie, self._days = page["movie"], page["days"]
        self._show_movie()
        if not self._days:
            self._day = self._session_id = None
            self.day_var.set("Нет сеансов")
            self._render_times()
            self._reset_map("На этот фильм сейчас нет доступных сеансов.")
            return
        self._day = date_iso if date_iso in self._days else next(iter(self._days))
        self._select_day(self._day, reselect)

    def _show_movie(self):
        m = self._movie
        self.title_label.configure(text=m["title"])
        self.poster.delete("all")
        self._thumb = neon.poster_thumb(movie_service.poster_file(m["poster_path"]), m["id"])
        if self._thumb is not None:
            self.poster.create_image(0, 0, image=self._thumb, anchor="nw")
        self.meta_label.configure(text=f"{m['genre_name']} · {format_duration(m['duration'])} · {m['age_rating']}")
        self.desc_label.configure(text=(m["description"] or "Описание не указано.").strip())

    def _back(self):
        if self.on_back:
            self.on_back()

    # ------------------------------------------------------------------ дата и время
    def _shift_day(self, step):
        days = list(self._days)
        if self._day in days:
            self._select_day(days[(days.index(self._day) + step) % len(days)])

    def _render_times(self):
        for child in self.times_row.winfo_children():
            child.destroy()
        for session in self._days.get(self._day, ()):
            SessionCard(self.times_row, session, session["id"] == self._session_id, self._open_session).pack(pady=(0, 6))

    def _select_day(self, day, reselect=None):
        self._day = day
        sessions = self._days[day]
        free = next((s for s in sessions if s["seats_free"] > 0), sessions[0])
        self.day_var.set(day_caption(day, clock.now().date()))
        self._open_session(reselect if reselect in {s["id"] for s in sessions} else free["id"])

    # ------------------------------------------------------------------ схема зала
    def _reset_map(self, message=""):
        self._seat_data, self._selected = None, set()
        self.info_var.set(message)
        for var in (self.selection_var, self.total_var, self.seat_var):
            var.set("")
        self.seat_map.render([])
        self.buy_button.set_enabled(False)

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
        self.error_var.set("" if data["is_open_for_sale"] else "Сеанс уже начался — покупка закрыта.")
        self.seat_var.set("")
        self._redraw()

    def _redraw(self):
        data = self._seat_data
        self.seat_map.render(data["rows"], self._selected)
        labels, total = selection_summary(data["rows"], self._selected, data["session"]["price"])
        vip = sum(1 for row in data["rows"] for s in row["seats"] if s["id"] in self._selected and s["seat_type"] == "vip")
        if labels:
            self.selection_var.set(f"{seats_caption(data['rows'], self._selected)}\nБилетов: {len(labels)}"
                                   + (f", из них VIP: {vip}" if vip else ""))
        else:
            self.selection_var.set("Нажмите на свободные кресла." if data["is_open_for_sale"] else "")
        self.total_var.set(f"Итого {format_price(total)}" if labels else "")
        self.buy_button.set_enabled(bool(labels) and data["is_open_for_sale"])

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
            self.error_var.set(f"За один заказ — не более {ticket_service.MAX_SEATS_PER_PURCHASE} мест.")
            return
        else:
            self._selected.add(seat["id"])
        self.error_var.set("")
        self._redraw()

    # ------------------------------------------------------------------ заказ
    def _seat_order(self):
        return [s["id"] for row in self._seat_data["rows"] for s in row["seats"] if s["id"] in self._selected]

    def _labels_of(self, seat_ids):
        wanted = set(seat_ids)
        return "; ".join(f"ряд {row['row_number']}, место {s['seat_number']}"
                         for row in self._seat_data["rows"] for s in row["seats"] if s["id"] in wanted)

    def _to_checkout(self):
        if self.user.client_id is None:
            self.error_var.set("Учётная запись не привязана к покупателю — купить билет нельзя.")
            return
        if self._seat_data is None or not self._selected:
            self.error_var.set("Выберите кресла на схеме.")
            return
        session_id, seat_ids = self._session_id, self._seat_order()
        ok, quote = guarded(self, buyer_service.quote, self.user, session_id, seat_ids)   # актуальная доступность
        if not ok:
            return
        if quote["unavailable"]:
            labels = self._labels_of(quote["unavailable"])
            self._open_session(session_id, keep=set(seat_ids))
            self.error_var.set(f"Место уже занято: {labels}. Схема обновлена.")
            messagebox.showwarning("Место недоступно", f"Эти места уже заняты: {labels}.\n"
                                   "Схема обновлена — выберите другие места.", parent=self)
            return
        if not quote["open"] or not quote["count"]:
            self.error_var.set("Покупка на этот сеанс закрыта.")
            return
        CheckoutDialog(self, quote, self._movie, lambda card: self._confirm(card, session_id, seat_ids))

    def _confirm(self, card, session_id, seat_ids):
        ok, result = guarded(self, buyer_service.place_order, self.user, session_id, seat_ids, card)
        if not ok:      # например, место успели занять: обновляем схему, свободные выбранные оставляем
            self._open_session(session_id, keep=set(seat_ids))
            return False
        for t in result["tickets"]:
            t["movie_id"], t["poster_path"] = self._movie["id"], self._movie["poster_path"]
        self.load(self._day, reselect=session_id)
        messagebox.showinfo("Заказ оформлен", f"Заказ № {result['order_id']} оплачен.\n"
                            f"Билетов: {len(result['tickets'])}, сумма: {format_price(result['total'])}.\n"
                            "Билеты сохранены в разделе «Мои билеты».", parent=self)
        ETicketDialog(self, result["tickets"])
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
                    self.error_var.set(f"Место уже занято: {self._labels_of(lost)}.")
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
