"""История покупок покупателя: только свои заказы; поиск по номеру, фильтры по датам и статусу, подробности и билеты."""
import tkinter as tk
from tkinter import ttk

from services import buyer_service

from .buyer_dialogs import ETicketDialog
from .common import MUTED_COLOR, guarded
from .formatting import date_ru_from_iso, datetime_ru, format_price
from .widgets import Combo, DataTable

COLUMNS = (("id", "Заказ №", 70), ("when", "Дата покупки", 120), ("movie", "Фильм", 190), ("session", "Сеанс", 130),
           ("count", "Билетов", 65), ("total", "Сумма", 85), ("status", "Статус", 130))
STATUS_OPTIONS = ((None, "Все"),) + buyer_service.ORDER_STATUSES
STATUS_TITLES = dict(buyer_service.ORDER_STATUSES)


class BuyerOrdersFrame(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.navigate = None
        self.id_var, self.from_var, self.to_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.info_var, self.details_var = tk.StringVar(), tk.StringVar()
        self._orders = {}
        self._build_ui()
        self.search()

    def _build_ui(self):
        ttk.Label(self, text="История покупок", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="№ заказа:").pack(side="left", padx=(0, 3))
        entry = ttk.Entry(bar, textvariable=self.id_var, width=8)
        entry.pack(side="left", padx=(0, 8))
        entry.bind("<Return>", lambda event: self.search())
        ttk.Label(bar, text="Период с").pack(side="left", padx=(0, 3))
        for var, tail in ((self.from_var, "по"), (self.to_var, None)):
            e = ttk.Entry(bar, textvariable=var, width=11, justify="center")
            e.pack(side="left", padx=(0, 4))
            e.bind("<Return>", lambda event: self.search())
            if tail:
                ttk.Label(bar, text=tail).pack(side="left", padx=(0, 4))
        ttk.Label(bar, text="Статус:").pack(side="left", padx=(8, 3))
        self.status_combo = Combo(bar, STATUS_OPTIONS, width=20, on_change=self.search)
        self.status_combo.set_value(None)
        self.status_combo.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Найти", command=self.search).pack(side="left")
        ttk.Button(bar, text="Сбросить", command=self.reset).pack(side="left", padx=6)

        self.table = DataTable(self, COLUMNS, height=12, on_select=self._on_select, on_activate=self._show_tickets)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, textvariable=self.details_var, justify="left", wraplength=760).pack(anchor="w", pady=(8, 0))
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(8, 0))
        self.show_button = ttk.Button(bottom, text="Открыть билеты заказа", command=self._show_tickets)
        self.show_button.pack(side="left")
        ttk.Label(bottom, textvariable=self.info_var, foreground=MUTED_COLOR).pack(side="left", padx=12)
        ttk.Label(self, text="Здесь только ваши заказы. Даты: ДД.ММ.ГГГГ.", foreground=MUTED_COLOR).pack(anchor="w", pady=(4, 0))

    def search(self):
        ok, orders = guarded(self, buyer_service.list_my_orders, self.user, order_id=self.id_var.get(),
                             date_from=self.from_var.get(), date_to=self.to_var.get(), status=self.status_combo.value())
        if not ok:
            return
        self._orders = {o["id"]: o for o in orders}
        self.table.set_rows(
            (o["id"], (o["id"], datetime_ru(o["created_at"]), o["movie_title"],
                       f"{date_ru_from_iso(o['session_date'])[:5]} {o['session_time']}, {o['hall_name']}",
                       o["tickets_total"], format_price(o["total"]), STATUS_TITLES[o["status"]]),
             "returned" if o["status"] == "returned" else None) for o in orders)
        self.info_var.set(f"Заказов: {len(orders)}" if orders else "Заказов не найдено.")
        self._on_select()

    def reset(self):
        for var in (self.id_var, self.from_var, self.to_var):
            var.set("")
        self.status_combo.set_value(None)
        self.search()

    def _selected(self):
        iid = self.table.selected_id()
        return self._orders.get(int(iid)) if iid is not None else None

    def _on_select(self):
        o = self._selected()
        self.show_button.configure(state="normal" if o else "disabled")
        if o is None:
            self.details_var.set("Выберите заказ, чтобы увидеть подробности.")
            return
        ok, tickets = guarded(self, buyer_service.get_order_tickets, self.user, o["id"])
        lines = [f"Заказ № {o['id']} · {STATUS_TITLES[o['status']]} · оплата: {o['payment_title']}"]
        if ok:
            lines.append("; ".join(f"№{t['id']} {t['seat_label']}" + (" (возвращён)" if t["status"] == "returned" else "")
                                   for t in tickets))
        self.details_var.set("\n".join(lines))

    def _show_tickets(self):
        o = self._selected()
        if o is None:
            return
        ok, tickets = guarded(self, buyer_service.get_order_tickets, self.user, o["id"])
        if ok and tickets:
            ETicketDialog(self, tickets)
