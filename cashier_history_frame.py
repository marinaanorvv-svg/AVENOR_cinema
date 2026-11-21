"""История продаж кассира: только собственные продажи; поиск по номеру, фильтры по дате, фильму и статусу."""
import tkinter as tk
from tkinter import ttk

from services import cashier_service, movie_service

from .cashier_dialogs import TicketDialog
from .common import MUTED_COLOR, guarded
from .formatting import STATUS_TITLES, date_ru_from_iso, datetime_ru, format_price
from .widgets import Combo, DataTable

COLUMNS = (("id", "№", 50), ("when", "Дата и время", 120), ("movie", "Фильм", 170), ("session", "Сеанс", 120),
           ("count", "Билетов", 60), ("total", "Сумма", 80), ("payment", "Оплата", 110), ("status", "Статус", 130))
STATUS_OPTIONS = ((None, "Все"),) + cashier_service.SALE_STATUSES
SALE_STATUS_TITLES = dict(cashier_service.SALE_STATUSES)


class CashierHistoryFrame(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.navigate = None
        self.id_var, self.from_var, self.to_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.info_var, self.details_var = tk.StringVar(), tk.StringVar()
        self._sales = {}
        self._build_ui()
        self._load_movies()
        self.search()

    def _build_ui(self):
        ttk.Label(self, text="История продаж", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="№ продажи:").pack(side="left", padx=(0, 3))
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
        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", pady=(0, 8))
        ttk.Label(bar2, text="Фильм:").pack(side="left", padx=(0, 3))
        self.movie_combo = Combo(bar2, [(None, "Все")], width=22, on_change=self.search)
        self.movie_combo.set_value(None)
        self.movie_combo.pack(side="left", padx=(0, 8))
        ttk.Label(bar2, text="Статус:").pack(side="left", padx=(0, 3))
        self.status_combo = Combo(bar2, STATUS_OPTIONS, width=20, on_change=self.search)
        self.status_combo.set_value(None)
        self.status_combo.pack(side="left", padx=(0, 8))
        ttk.Button(bar2, text="Найти", command=self.search).pack(side="left")
        ttk.Button(bar2, text="Сбросить", command=self.reset).pack(side="left", padx=6)

        self.table = DataTable(self, COLUMNS, height=11, on_select=self._on_select)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, textvariable=self.details_var, justify="left", wraplength=760).pack(anchor="w", pady=(8, 0))
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(8, 0))
        self.show_button = ttk.Button(bottom, text="Показать билеты", command=self._show_tickets)
        self.show_button.pack(side="left")
        ttk.Label(bottom, textvariable=self.info_var, foreground=MUTED_COLOR).pack(side="left", padx=12)
        ttk.Label(self, text="Здесь только ваши продажи. Даты: ДД.ММ.ГГГГ.", foreground=MUTED_COLOR).pack(anchor="w", pady=(4, 0))

    def _load_movies(self):
        ok, movies = guarded(self, movie_service.list_movies, self.user)
        if ok:
            self.movie_combo.set_options([(None, "Все")] + [(m["id"], m["title"]) for m in movies])
            self.movie_combo.set_value(None)

    def search(self):
        ok, sales = guarded(self, cashier_service.list_my_sales, self.user, sale_id=self.id_var.get(),
                            date_from=self.from_var.get(), date_to=self.to_var.get(),
                            movie_id=self.movie_combo.value(), status=self.status_combo.value())
        if not ok:
            return
        self._sales = {s["id"]: s for s in sales}
        self.table.set_rows(
            (s["id"], (s["id"], datetime_ru(s["created_at"]), s["movie_title"],
                       f"{date_ru_from_iso(s['session_date'])[:5]} {s['session_time']}, {s['hall_name']}",
                       s["tickets_total"], format_price(s["total"]), s["payment_title"],
                       SALE_STATUS_TITLES[s["status"]]), "returned" if s["status"] == "returned" else None)
            for s in sales)
        total = sum(s["total"] for s in sales)
        self.info_var.set(f"Продаж: {len(sales)} на {format_price(total)}")
        self._on_select()

    def reset(self):
        for var in (self.id_var, self.from_var, self.to_var):
            var.set("")
        self.movie_combo.set_value(None)
        self.status_combo.set_value(None)
        self.search()

    def _selected(self):
        iid = self.table.selected_id()
        return self._sales.get(int(iid)) if iid is not None else None

    def _on_select(self):
        s = self._selected()
        self.show_button.configure(state="normal" if s else "disabled")
        if s is None:
            self.details_var.set("Выберите продажу, чтобы увидеть подробности.")
            return
        ok, tickets = guarded(self, cashier_service.get_sale_tickets, self.user, s["id"])
        lines = [f"Продажа № {s['id']} · {SALE_STATUS_TITLES[s['status']]} · покупатель: {s['client_name']}"]
        if ok:
            lines.append("; ".join(f"№{t['id']} {t['seat_label']} ({STATUS_TITLES.get(t['status'], t['status'])})"
                                   for t in tickets))
        self.details_var.set("\n".join(lines))

    def _show_tickets(self):
        s = self._selected()
        if s is None:
            return
        ok, tickets = guarded(self, cashier_service.get_sale_tickets, self.user, s["id"])
        if ok and tickets:
            TicketDialog(self, tickets)
