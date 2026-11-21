"""Поиск и возврат билетов (кассир/админ) и «Мои билеты» (пользователь)."""
import tkinter as tk
from tkinter import messagebox, ttk

from services import ticket_service
from services.permissions import Permission

from .common import ask_confirm, guarded, MUTED_COLOR
from .formatting import date_ru_from_iso, format_price, ticket_row, ticket_tag
from .widgets import Combo, DataTable

TICKET_COLUMNS = (("id", "№", 50), ("movie", "Фильм", 190), ("date", "Дата", 90), ("time", "Время", 60),
                  ("hall", "Зал", 80), ("seat", "Место", 120), ("client", "Клиент", 150),
                  ("price", "Цена", 80), ("status", "Статус", 90), ("bought", "Куплен", 120))
STATUS_OPTIONS = ((None, "Все"), ("sold", "Проданные"), ("returned", "Возвращённые"))
MAX_ROWS = 500


class TicketsFrame(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.id_var, self.client_var, self.date_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.info_var = tk.StringVar()
        self._tickets = {}
        self._build_ui()
        self.search()

    def _build_ui(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        for label, var, width in (("№ билета:", self.id_var, 8), ("Клиент:", self.client_var, 22),
                                  ("Дата сеанса:", self.date_var, 12)):
            ttk.Label(bar, text=label).pack(side="left", padx=(0, 4))
            entry = ttk.Entry(bar, textvariable=var, width=width)
            entry.pack(side="left", padx=(0, 10))
            entry.bind("<Return>", lambda event: self.search())
        ttk.Label(bar, text="Статус:").pack(side="left", padx=(0, 4))
        self.status_combo = Combo(bar, STATUS_OPTIONS, width=14)
        self.status_combo.set_value(None)
        self.status_combo.pack(side="left", padx=(0, 10))
        ttk.Button(bar, text="Найти", command=self.search).pack(side="left")
        ttk.Button(bar, text="Сбросить", command=self._reset_filters).pack(side="left", padx=6)

        self.table = DataTable(self, TICKET_COLUMNS, height=16, on_select=self._on_select)
        self.table.pack(fill="both", expand=True)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(8, 0))
        self.refund_button = ttk.Button(bottom, text="Вернуть билет", command=self._refund)
        self.refund_button.pack(side="left")
        self.refund_button.configure(state="disabled")
        ttk.Label(bottom, textvariable=self.info_var, foreground=MUTED_COLOR).pack(side="left", padx=12)
        ttk.Label(self, text="Серым выделены возвращённые билеты и билеты на уже начавшиеся сеансы "
                             "(их вернуть нельзя).", foreground=MUTED_COLOR).pack(anchor="w", pady=(6, 0))

    def search(self):
        ok, tickets = guarded(self, ticket_service.search_tickets, self.user,
                              ticket_id=self.id_var.get(), client=self.client_var.get(),
                              date=self.date_var.get(), status=self.status_combo.value())
        if not ok:
            return
        shown = tickets[:MAX_ROWS]
        self._tickets = {t["id"]: t for t in shown}
        self.table.set_rows((t["id"], ticket_row(t), ticket_tag(t) or None) for t in shown)
        self.info_var.set(f"Найдено билетов: {len(tickets)}"
                          + (f" (показаны первые {MAX_ROWS})" if len(tickets) > MAX_ROWS else ""))
        self._on_select()

    def _reset_filters(self):
        for var in (self.id_var, self.client_var, self.date_var):
            var.set("")
        self.status_combo.set_value(None)
        self.search()

    def _selected_ticket(self):
        iid = self.table.selected_id()
        return self._tickets.get(int(iid)) if iid is not None else None

    def _on_select(self):
        ticket = self._selected_ticket()
        can = bool(ticket and ticket["is_refundable"] and self.user.has_permission(Permission.REFUND_TICKET))
        self.refund_button.configure(state="normal" if can else "disabled")

    def _refund(self):
        ticket = self._selected_ticket()
        if ticket is None:
            messagebox.showinfo("Выбор", "Выберите билет в таблице.", parent=self)
            return
        question = (f"Вернуть билет №{ticket['id']}?\n{ticket['movie_title']}, "
                    f"{date_ru_from_iso(ticket['session_date'])} {ticket['session_time']}, {ticket['seat_label']}\n"
                    f"Сумма к возврату: {format_price(ticket['price'])}")
        if not ask_confirm(self, question):
            return
        ok, result = guarded(self, ticket_service.refund_ticket, self.user, ticket["id"])
        if ok:
            messagebox.showinfo("Возврат оформлен",
                                f"Билет №{result['id']} возвращён.\nСумма к возврату: {format_price(result['price'])}",
                                parent=self)
        self.search()   # в любом случае обновляем таблицу: данные могли измениться


class MyTicketsFrame(ttk.Frame):
    """История билетов пользователя. Возврат — только через кассу (по ТЗ у зрителя такого права нет)."""

    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.info_var = tk.StringVar()
        columns = TICKET_COLUMNS[:6] + TICKET_COLUMNS[7:9]   # без клиента (это всегда сам пользователь) и даты покупки
        ttk.Label(self, text="Мои билеты", style="Header.TLabel").pack(anchor="w")
        self.table = DataTable(self, columns, height=16)
        self.table.pack(fill="both", expand=True, pady=8)
        bottom = ttk.Frame(self)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Обновить", command=self.load).pack(side="left")
        ttk.Label(bottom, textvariable=self.info_var, foreground=MUTED_COLOR).pack(side="left", padx=12)
        ttk.Label(self, text="Возврат билета оформляется на кассе кинотеатра до начала сеанса.",
                  foreground=MUTED_COLOR).pack(anchor="w", pady=(6, 0))
        self.load()

    def load(self):
        ok, tickets = guarded(self, ticket_service.list_my_tickets, self.user)
        if not ok:
            return
        self.table.set_rows(
            (t["id"], ticket_row(t)[:6] + ticket_row(t)[7:9], ticket_tag(t) or None) for t in tickets)
        self.info_var.set(f"Билетов: {len(tickets)}" if tickets else "У вас пока нет билетов.")
