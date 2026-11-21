"""Поиск билетов (кассир): номер, фильм, дата, номер сеанса, покупатель, статус; подробности выбранного билета."""
import tkinter as tk
from tkinter import ttk

from services import cashier_service, clock

from .cashier_dialogs import TicketDialog
from .common import MUTED_COLOR, guarded
from .formatting import (STATUS_TITLES, date_ru_from_iso, datetime_ru, format_price, ticket_tag)
from .widgets import Combo, DataTable

COLUMNS = (("id", "№", 50), ("movie", "Фильм", 170), ("session", "Сеанс", 120), ("hall", "Зал", 70),
           ("seat", "Место", 110), ("client", "Покупатель", 130), ("price", "Цена", 70), ("status", "Статус", 85))
STATUS_OPTIONS = ((None, "Все"), ("sold", "Проданные"), ("returned", "Возвращённые"))
MAX_ROWS = 300


def ticket_details_text(t: dict) -> str:
    status = STATUS_TITLES.get(t["status"], t["status"])
    if t["status"] == "returned" and t.get("returned_at"):
        status += f" ({datetime_ru(t['returned_at'])})"
    note = f"\nВозврат недоступен: {t['refund_reason']}" if t["status"] == "sold" and t.get("refund_reason") else ""
    return (f"Билет № {t['id']} · {status}\n"
            f"«{t['movie_title']}», сеанс № {t['session_id']}: {date_ru_from_iso(t['session_date'])} {t['session_time']}, "
            f"зал «{t['hall_name']}», {t['seat_label']}\n"
            f"Стоимость {format_price(t['price'])} · куплен {datetime_ru(t['purchase_date'])} · покупатель: {t['client_name']}" + note)


class CashierSearchFrame(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.navigate = None
        self.vars = {k: tk.StringVar() for k in ("id", "movie", "date", "session", "client")}
        self.details_var, self.info_var = tk.StringVar(), tk.StringVar()
        self._tickets = {}
        self._build_ui()
        self.search()

    def _build_ui(self):
        ttk.Label(self, text="Поиск билетов", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))
        for key, caption, width in (("id", "№ билета", 8), ("movie", "Фильм", 18), ("date", "Дата сеанса", 11),
                                    ("session", "№ сеанса", 8), ("client", "Покупатель", 16)):
            ttk.Label(bar, text=caption + ":").pack(side="left", padx=(0, 3))
            entry = ttk.Entry(bar, textvariable=self.vars[key], width=width)
            entry.pack(side="left", padx=(0, 8))
            entry.bind("<Return>", lambda event: self.search())
        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", pady=(0, 8))
        ttk.Label(bar2, text="Статус:").pack(side="left", padx=(0, 3))
        self.status_combo = Combo(bar2, STATUS_OPTIONS, width=14, on_change=self.search)
        self.status_combo.set_value(None)
        self.status_combo.pack(side="left")
        ttk.Button(bar2, text="Найти", command=self.search).pack(side="left", padx=8)
        ttk.Button(bar2, text="Сбросить", command=self.reset).pack(side="left")
        ttk.Label(bar2, textvariable=self.info_var, foreground=MUTED_COLOR).pack(side="left", padx=10)
        ttk.Label(bar2, text="Дата: ДД.ММ.ГГГГ", foreground=MUTED_COLOR).pack(side="right")

        self.table = DataTable(self, COLUMNS, height=11, on_select=self._on_select)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, textvariable=self.details_var, justify="left", wraplength=760).pack(anchor="w", pady=(8, 0))
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(8, 0))
        self.show_button = ttk.Button(bottom, text="Показать билет", command=self._show_ticket)
        self.show_button.pack(side="left")
        self.refund_button = ttk.Button(bottom, text="Перейти к возврату", command=self._to_refund)
        self.refund_button.pack(side="left", padx=6)

    def search(self):
        v = {k: var.get() for k, var in self.vars.items()}
        ok, tickets = guarded(self, cashier_service.search_tickets, self.user, ticket_id=v["id"] or None,
                              movie=v["movie"], date=v["date"] or None, session_id=v["session"] or None,
                              client=v["client"], status=self.status_combo.value())
        if not ok:
            return
        shown = tickets[:MAX_ROWS]
        self._tickets = {t["id"]: t for t in shown}
        self.table.set_rows(
            (t["id"], (t["id"], t["movie_title"], f"{date_ru_from_iso(t['session_date'])[:5]} {t['session_time']}",
                       t["hall_name"], t["seat_label"], t["client_name"], format_price(t["price"]),
                       STATUS_TITLES.get(t["status"], t["status"])), ticket_tag(t) or None) for t in shown)
        self.info_var.set(f"Найдено: {len(tickets)}" + (f" (показаны первые {MAX_ROWS})" if len(tickets) > MAX_ROWS else ""))
        self._on_select()

    def reset(self):
        for var in self.vars.values():
            var.set("")
        self.status_combo.set_value(None)
        self.search()

    def _selected(self):
        iid = self.table.selected_id()
        return self._tickets.get(int(iid)) if iid is not None else None

    def _on_select(self):
        t = self._selected()
        self.details_var.set(ticket_details_text(t) if t else "Выберите билет в таблице, чтобы увидеть подробности.")
        self.show_button.configure(state="normal" if t else "disabled")
        self.refund_button.configure(state="normal" if t and t["is_refundable"] else "disabled")

    def _show_ticket(self):
        t = self._selected()
        if t is not None:
            TicketDialog(self, [t])

    def _to_refund(self):
        t = self._selected()
        if t is not None and self.navigate:
            self.navigate("refund", ticket_id=t["id"])
