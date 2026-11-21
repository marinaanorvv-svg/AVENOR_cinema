"""Возврат билетов (кассир): номер -> подробности -> проверка правил -> подтверждение -> фиксация возврата."""
import tkinter as tk
from tkinter import messagebox, ttk

from services import cashier_service

from .cashier_search_frame import ticket_details_text
from .common import ERROR_COLOR, MUTED_COLOR, ask_confirm, guarded
from .formatting import datetime_ru, format_price
from .widgets import DataTable

RECENT = (("number", "Билет №", 70), ("time", "Время возврата", 140), ("movie", "Фильм", 220), ("amount", "Сумма", 90))
GOOD_COLOR = "#7be0a1"


class CashierRefundFrame(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.navigate = None
        self.id_var, self.details_var, self.verdict_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self._ticket = None
        self._build_ui()
        self.load_recent()

    def _build_ui(self):
        ttk.Label(self, text="Возврат билетов", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Номер билета:").pack(side="left", padx=(0, 4))
        entry = ttk.Entry(bar, textvariable=self.id_var, width=12)
        entry.pack(side="left", padx=(0, 8))
        entry.bind("<Return>", lambda event: self.find())
        ttk.Button(bar, text="Найти", command=self.find).pack(side="left")
        ttk.Label(bar, text="Нужного номера нет? Используйте «Поиск билетов».", foreground=MUTED_COLOR).pack(side="left", padx=12)

        ttk.Label(self, textvariable=self.details_var, justify="left", wraplength=760).pack(anchor="w")
        self.verdict_label = ttk.Label(self, textvariable=self.verdict_var, wraplength=760)
        self.verdict_label.pack(anchor="w", pady=(6, 0))
        self.refund_button = ttk.Button(self, text="Оформить возврат", command=self.refund)
        self.refund_button.pack(anchor="w", pady=(8, 10))
        self.refund_button.configure(state="disabled")
        ttk.Label(self, text="Мои последние возвраты", style="Muted.TLabel").pack(anchor="w")
        self.table = DataTable(self, RECENT, height=8)
        self.table.pack(fill="both", expand=True)

    def load_ticket(self, ticket_id):
        """Подставляет номер (переход из поиска) и сразу проверяет билет."""
        self.id_var.set(str(ticket_id))
        self.find()

    def find(self):
        self._ticket = None
        self.refund_button.configure(state="disabled")
        ok, check = guarded(self, cashier_service.refund_check, self.user, self.id_var.get())
        if not ok:
            self.details_var.set("")
            self.verdict_var.set("")
            return
        self._ticket = check["ticket"]
        self.details_var.set(ticket_details_text(check["ticket"]))
        self.verdict_var.set("Возврат возможен: билет действующий, сеанс ещё не начался." if check["can_refund"]
                             else check["reason"])
        self.verdict_label.configure(foreground=GOOD_COLOR if check["can_refund"] else ERROR_COLOR)
        self.refund_button.configure(state="normal" if check["can_refund"] else "disabled")

    def refund(self):
        t = self._ticket
        if t is None:
            messagebox.showinfo("Выбор", "Сначала найдите билет по номеру.", parent=self)
            return
        if not ask_confirm(self, f"Оформить возврат билета № {t['id']}?\n{t['movie_title']}, {t['seat_label']}\n"
                                 f"Сумма к возврату: {format_price(t['price'])}"):
            return
        ok, result = guarded(self, cashier_service.refund, self.user, t["id"])
        if ok:
            messagebox.showinfo("Возврат оформлен", f"Билет № {result['id']} возвращён, место свободно.\n"
                                f"Верните клиенту {format_price(result['price'])}.", parent=self)
        self.find()
        self.load_recent()

    def load_recent(self):
        ok, ops = guarded(self, cashier_service.recent_operations, self.user, 60)
        if ok:
            self.table.set_rows((o["number"], (o["number"], datetime_ru(o["time"]), o["movie"],
                                               format_price(-o["amount"])), None)
                                for o in ops if o["kind"] == "refund")
