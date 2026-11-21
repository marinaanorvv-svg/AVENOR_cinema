"""Рабочая смена кассира: открытие, итоги по ходу работы, завершение с итоговым отчётом, список прошлых смен."""
import tkinter as tk
from tkinter import ttk

from services import cashier_service

from .cashier_dialogs import TextReportDialog
from .common import MUTED_COLOR, ask_confirm, guarded
from .formatting import datetime_ru, format_price
from .widgets import DataTable

METRICS = (("metric", "Показатель", 230), ("value", "Значение", 160))
HISTORY = (("id", "Смена", 60), ("opened", "Открыта", 120), ("closed", "Закрыта", 120), ("sales", "Продаж", 60),
           ("tickets", "Билетов", 60), ("returns", "Возвратов", 70), ("net", "Итого", 100))


def summary_rows(summary: dict) -> list[tuple[str, str]]:
    rows = [("Продаж", str(summary["sales_count"])), ("Продано билетов", str(summary["tickets_sold"])),
            ("Сумма продаж", format_price(summary["sales_amount"])),
            ("Возвратов (билетов)", str(summary["returns_count"])),
            ("Сумма возвратов", format_price(summary["refund_amount"])),
            ("Итого за смену", format_price(summary["net_amount"]))]
    rows += [(f"  {m['title']}", format_price(m["net"])) for m in summary["by_method"]]
    return rows


class CashierShiftFrame(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.navigate = None
        self.status_var = tk.StringVar()
        self._shifts = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        ttk.Label(self, text="Рабочая смена", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w")
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=8)
        self.open_button = ttk.Button(buttons, text="Открыть смену", command=self.open_shift)
        self.open_button.pack(side="left")
        self.close_button = ttk.Button(buttons, text="Завершить смену", command=self.close_shift)
        self.close_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="Обновить", command=self.refresh).pack(side="left")
        ttk.Label(self, text="Итоги текущей смены", style="Muted.TLabel").pack(anchor="w")
        self.metrics = DataTable(self, METRICS, height=9)
        self.metrics.pack(fill="x")
        ttk.Label(self, text="Прошлые смены", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        self.history = DataTable(self, HISTORY, height=6, on_activate=self.show_report)
        self.history.pack(fill="both", expand=True)
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", pady=(6, 0))
        ttk.Button(bottom, text="Показать отчёт по смене", command=self.show_report).pack(side="left")
        ttk.Label(bottom, text="Продажа и возврат возможны только при открытой смене.",
                  foreground=MUTED_COLOR).pack(side="left", padx=10)

    def refresh(self):
        ok, summary = guarded(self, cashier_service.shift_summary, self.user)
        if not ok:
            return
        shift = summary["shift"]
        if shift:
            self.status_var.set(f"Смена № {shift['id']} открыта с {datetime_ru(shift['opened_at'])}")
        else:
            self.status_var.set("Смена не открыта.")
        self.open_button.configure(state="disabled" if shift else "normal")
        self.close_button.configure(state="normal" if shift else "disabled")
        self.metrics.set_rows((i, row, None) for i, row in enumerate(summary_rows(summary)))
        ok, shifts = guarded(self, cashier_service.list_my_shifts, self.user)
        if ok:
            self._shifts = {s["shift"]["id"]: s for s in shifts}
            self.history.set_rows(
                (s["shift"]["id"], (s["shift"]["id"], datetime_ru(s["shift"]["opened_at"]),
                                    datetime_ru(s["shift"]["closed_at"]) if s["shift"]["closed_at"] else "идёт",
                                    s["sales_count"], s["tickets_sold"], s["returns_count"],
                                    format_price(s["net_amount"])), None) for s in shifts)

    def open_shift(self):
        ok, _ = guarded(self, cashier_service.open_shift, self.user)
        self.refresh()

    def close_shift(self):
        if not ask_confirm(self, "Завершить смену? После этого продажи и возвраты будут недоступны, "
                                 "пока вы не откроете новую смену."):
            return
        ok, summary = guarded(self, cashier_service.close_shift, self.user)
        self.refresh()
        if ok:
            self._report(summary)

    def show_report(self):
        iid = self.history.selected_id()
        if iid is None:
            ok, summary = guarded(self, cashier_service.shift_summary, self.user)
            if ok and summary["shift"]:
                self._report(summary)
            return
        ok, summary = guarded(self, cashier_service.shift_summary, self.user, int(iid))
        if ok:
            self._report(summary)

    def _report(self, summary):
        shift_id = summary["shift"]["id"] if summary["shift"] else 0
        TextReportDialog(self, "Итоги смены", cashier_service.shift_report_text(summary, self.user.full_name),
                         filename=f"shift_{shift_id}.txt")
