"""Билеты для администратора: полный просмотр, поиск и фильтры, подробности, возврат.

Отдельный экран: интерфейс кассира (tickets_frame.TicketsFrame) не затронут. Возврат делает тот же
ticket_service.refund_ticket, что и на кассе, — правила возврата не дублируются.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from services import admin_service, movie_service, ticket_service
from services.permissions import Permission

from .common import MUTED_COLOR, ask_confirm, guarded
from .formatting import date_ru_from_iso, datetime_ru, format_price, ticket_tag, STATUS_TITLES
from .widgets import Combo, DataTable

COLUMNS = (("id", "№", 50), ("movie", "Фильм", 180), ("date", "Сеанс", 110), ("hall", "Зал", 70),
           ("seat", "Место", 110), ("client", "Покупатель", 140), ("price", "Цена", 75),
           ("status", "Статус", 90), ("bought", "Куплен", 120))
STATUS_OPTIONS = ((None, "Все"), ("sold", "Проданные"), ("returned", "Возвращённые"))
MAX_ROWS = 500


def admin_ticket_row(t: dict) -> tuple:
    status = STATUS_TITLES.get(t["status"], t["status"])
    if t.get("session_cancelled"):
        status = "Сеанс отменён"
    return (t["id"], t["movie_title"], f"{date_ru_from_iso(t['session_date'])[:5]} {t['session_time']}",
            t["hall_name"], t["seat_label"], t["client_name"], format_price(t["price"]), status,
            datetime_ru(t["purchase_date"]))


def ticket_details(t: dict) -> str:
    """Подробности выбранного билета одной строкой-абзацем под таблицей."""
    parts = [f"Билет №{t['id']}: «{t['movie_title']}», {date_ru_from_iso(t['session_date'])} {t['session_time']}, "
             f"зал «{t['hall_name']}», {t['seat_label']}{' (VIP)' if t['seat_type'] == 'vip' else ''}.",
             f"Стоимость {format_price(t['price'])}. Куплен {datetime_ru(t['purchase_date'])}; оформил: {t['seller_label']}.",
             f"Покупатель: {t['client_name']}"
             + (f", тел. {t['client_phone']}" if t["client_phone"] else "")
             + (f", {t['client_email']}" if t["client_email"] else "") + "."]
    if t["status"] == "returned":
        parts.append(f"Возвращён {datetime_ru(t['returned_at'])}." if t["returned_at"] else "Возвращён.")
    elif t.get("refund_reason"):
        parts.append(f"Возврат недоступен: {t['refund_reason']}")
    return "\n".join(parts)


class AdminTicketsFrame(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.id_var, self.client_var = tk.StringVar(), tk.StringVar()
        self.s_from, self.s_to = tk.StringVar(), tk.StringVar()
        self.b_from, self.b_to = tk.StringVar(), tk.StringVar()
        self.info_var, self.details_var = tk.StringVar(), tk.StringVar()
        self._tickets = {}
        self._build_ui()
        self._load_movies()
        self.search()

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 6))
        for label, var, width in (("№ билета:", self.id_var, 8), ("Покупатель:", self.client_var, 20)):
            ttk.Label(top, text=label).pack(side="left", padx=(0, 4))
            entry = ttk.Entry(top, textvariable=var, width=width)
            entry.pack(side="left", padx=(0, 10))
            entry.bind("<Return>", lambda event: self.search())
        ttk.Label(top, text="Фильм:").pack(side="left", padx=(0, 4))
        self.movie_combo = Combo(top, [(None, "Все фильмы")], width=22)
        self.movie_combo.set_value(None)
        self.movie_combo.pack(side="left", padx=(0, 10))
        ttk.Label(top, text="Статус:").pack(side="left", padx=(0, 4))
        self.status_combo = Combo(top, STATUS_OPTIONS, width=13)
        self.status_combo.set_value(None)
        self.status_combo.pack(side="left")

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        for label, a, b in (("Сеанс с", self.s_from, self.s_to), ("Куплен с", self.b_from, self.b_to)):
            ttk.Label(bar, text=label).pack(side="left", padx=(0, 4))
            for var, tail in ((a, " по "), (b, "")):
                entry = ttk.Entry(bar, textvariable=var, width=11, justify="center")
                entry.pack(side="left", padx=(0, 4))
                entry.bind("<Return>", lambda event: self.search())
                if tail:
                    ttk.Label(bar, text="по").pack(side="left", padx=(0, 4))
            ttk.Label(bar, text="  ").pack(side="left")
        ttk.Button(bar, text="Найти", command=self.search).pack(side="left")
        ttk.Button(bar, text="Сбросить", command=self._reset).pack(side="left", padx=6)

        self.table = DataTable(self, COLUMNS, height=12, on_select=self._on_select)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, textvariable=self.details_var, justify="left", wraplength=760).pack(anchor="w", pady=(8, 0))
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(8, 0))
        self.refund_button = ttk.Button(bottom, text="Оформить возврат", command=self._refund)
        self.refund_button.pack(side="left")
        self.refund_button.configure(state="disabled")
        ttk.Label(bottom, textvariable=self.info_var, foreground=MUTED_COLOR).pack(side="left", padx=12)
        ttk.Label(self, text="Даты: ДД.ММ.ГГГГ. Серым выделены возвращённые билеты и билеты на начавшиеся сеансы.",
                  foreground=MUTED_COLOR).pack(anchor="w", pady=(4, 0))

    def _load_movies(self):
        ok, movies = guarded(self, movie_service.list_movies, self.user)
        if ok:
            self.movie_combo.set_options([(None, "Все фильмы")] + [(m["id"], m["title"]) for m in movies])
            self.movie_combo.set_value(None)

    def search(self):
        ok, tickets = guarded(
            self, admin_service.search_tickets, self.user, ticket_id=self.id_var.get(), client=self.client_var.get(),
            movie_id=self.movie_combo.value(), status=self.status_combo.value(),
            session_from=self.s_from.get(), session_to=self.s_to.get(),
            bought_from=self.b_from.get(), bought_to=self.b_to.get())
        if not ok:
            return
        shown = tickets[:MAX_ROWS]
        self._tickets = {t["id"]: t for t in shown}
        self.table.set_rows((t["id"], admin_ticket_row(t), ticket_tag(t) or None) for t in shown)
        sold = [t for t in tickets if t["status"] == "sold"]
        self.info_var.set(f"Найдено: {len(tickets)}; действующих: {len(sold)} на {format_price(sum(t['price'] for t in sold))}"
                          + (f" (показаны первые {MAX_ROWS})" if len(tickets) > MAX_ROWS else ""))
        self._on_select()

    def _reset(self):
        for var in (self.id_var, self.client_var, self.s_from, self.s_to, self.b_from, self.b_to):
            var.set("")
        self.movie_combo.set_value(None)
        self.status_combo.set_value(None)
        self.search()

    def _selected(self):
        iid = self.table.selected_id()
        return self._tickets.get(int(iid)) if iid is not None else None

    def _on_select(self):
        ticket = self._selected()
        self.details_var.set(ticket_details(ticket) if ticket else "Выберите билет, чтобы увидеть подробности.")
        can = bool(ticket and ticket["is_refundable"] and self.user.has_permission(Permission.REFUND_TICKET))
        self.refund_button.configure(state="normal" if can else "disabled")

    def _refund(self):
        ticket = self._selected()
        if ticket is None:
            messagebox.showinfo("Выбор", "Выберите билет в таблице.", parent=self)
            return
        if not ask_confirm(self, f"Вернуть билет №{ticket['id']}?\n{ticket['movie_title']}, "
                                 f"{date_ru_from_iso(ticket['session_date'])} {ticket['session_time']}, "
                                 f"{ticket['seat_label']}\nСумма к возврату: {format_price(ticket['price'])}"):
            return
        ok, result = guarded(self, ticket_service.refund_ticket, self.user, ticket["id"])
        if ok:
            messagebox.showinfo("Возврат оформлен", f"Билет №{result['id']} возвращён.\n"
                                f"Сумма к возврату: {format_price(result['price'])}", parent=self)
        self.search()
