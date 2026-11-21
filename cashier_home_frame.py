"""Главная панель кассира: имя, дата и время, итоги текущей смены, ближайшие сеансы, последние операции."""
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from services import cashier_service, clock

from . import palette as P
from .common import MUTED_COLOR, guarded
from .dashboard_frame import StatCard
from .formatting import date_ru_from_iso, datetime_ru, format_price
from .widgets import DataTable

REFRESH_TICKS = 30     # данные обновляются раз в 30 секунд, часы — каждую секунду
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def clock_text(moment: datetime) -> str:
    """'пятница, 13.11.2026  11:43:05'."""
    return f"{WEEKDAYS[moment.weekday()]}, {moment.strftime('%d.%m.%Y')}  {moment.strftime('%H:%M:%S')}"


class CashierHomeFrame(ttk.Frame):
    CARDS = (("tickets", "Билетов за смену"), ("sales", "Сумма продаж"), ("returns", "Возвратов"),
             ("net", "Итого за смену"))
    UPCOMING = (("when", "Когда", 100), ("movie", "Фильм", 170), ("hall", "Зал", 70), ("free", "Свободно", 80))
    OPERATIONS = (("kind", "Операция", 90), ("number", "№", 50), ("time", "Время", 120), ("movie", "Фильм", 150),
                  ("amount", "Сумма", 90))

    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.navigate = None            # MainFrame подставляет open_screen: быстрые кнопки переходят в разделы
        self.clock_var, self.shift_var, self.hello_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.cards, self._job, self._ticks = {}, None, 0
        self._build_ui()
        self.refresh()
        self._schedule()

    def _build_ui(self):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 4))
        ttk.Label(head, textvariable=self.hello_var, style="Header.TLabel").pack(side="left")
        ttk.Label(head, textvariable=self.clock_var, foreground=MUTED_COLOR).pack(side="right")
        status = ttk.Frame(self)
        status.pack(fill="x", pady=(0, 8))
        ttk.Label(status, textvariable=self.shift_var).pack(side="left")
        ttk.Button(status, text="Обновить", command=self.refresh).pack(side="right")
        ttk.Button(status, text="Смена", command=lambda: self._go("shift")).pack(side="right", padx=6)
        ttk.Button(status, text="Возврат", command=lambda: self._go("refund")).pack(side="right")
        ttk.Button(status, text="Продать билеты", command=lambda: self._go("sale")).pack(side="right", padx=6)

        row = tk.Frame(self, bg=P.PANEL)
        row.pack(fill="x", pady=(0, 10))
        for index, (key, caption) in enumerate(self.CARDS):
            card = StatCard(row, caption)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 6, 0))
            row.columnconfigure(index, weight=1, uniform="cards")
            self.cards[key] = card

        middle = ttk.Frame(self)
        middle.pack(fill="both", expand=True)
        left = ttk.Frame(middle)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        ttk.Label(left, text="Ближайшие сеансы", style="Muted.TLabel").pack(anchor="w")
        self.upcoming_table = DataTable(left, self.UPCOMING, height=7)
        self.upcoming_table.pack(fill="both", expand=True)
        right = ttk.Frame(middle)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Последние операции", style="Muted.TLabel").pack(anchor="w")
        self.operations_table = DataTable(right, self.OPERATIONS, height=7)
        self.operations_table.pack(fill="both", expand=True)

    def _go(self, key):
        if self.navigate:
            self.navigate(key)

    # ------------------------------------------------------------------ данные
    def refresh(self):
        self._tick_clock()
        ok, data = guarded(self, cashier_service.dashboard, self.user)
        if not ok:
            return
        summary, shift = data["summary"], data["shift"]
        self.hello_var.set(f"Здравствуйте, {data['name']}")
        if shift:
            self.shift_var.set(f"Смена № {shift['id']} открыта с {datetime_ru(shift['opened_at'])[11:]}")
        else:
            self.shift_var.set("Смена не открыта — откройте её в разделе «Смена», чтобы продавать билеты.")
        self.cards["tickets"].show(summary["tickets_sold"], f"продаж: {summary['sales_count']}")
        self.cards["sales"].show(format_price(summary["sales_amount"]))
        self.cards["returns"].show(summary["returns_count"], f"на {format_price(summary['refund_amount'])}")
        self.cards["net"].show(format_price(summary["net_amount"]), "продажи − возвраты")
        self.upcoming_table.set_rows(
            (s["id"], (f"{date_ru_from_iso(s['date'])[:5]} {s['time']}", s["movie"], s["hall"],
                       f"{s['free']} из {s['total']}"), "soldout" if s["free"] == 0 else None)
            for s in data["upcoming"])
        self.operations_table.set_rows(
            (f"{o['kind']}{o['number']}", ("Продажа" if o["kind"] == "sale" else "Возврат", o["number"],
                                           datetime_ru(o["time"]), o["movie"], format_price(o["amount"])),
             "returned" if o["kind"] == "refund" else None) for o in data["operations"])

    def _tick_clock(self):
        self.clock_var.set(clock_text(clock.now()))

    # ------------------------------------------------------------------ часы и автообновление
    def _schedule(self):
        self._job = self.after(1000, self._tick)

    def _tick(self):
        self._job = None
        self._ticks += 1
        if self._ticks % REFRESH_TICKS == 0:
            self.refresh()
        else:
            self._tick_clock()
        self._schedule()

    def destroy(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        super().destroy()
