"""Отчёты (выручка, посещаемость и залы, продажи по кассирам) с экспортом в CSV (администратор)."""
import tkinter as tk
from datetime import timedelta
from tkinter import filedialog, messagebox, ttk

from services import clock, report_service
from services.errors import ServiceError

from .common import ERROR_COLOR, MUTED_COLOR, guarded
from .formatting import format_date_ru, format_report_cell, normalize_date_input, summary_text, today_ru
from .widgets import Combo, DataTable

REPORT_TYPES = (("revenue", "Выручка"), ("attendance", "Посещаемость и залы"), ("cashiers", "Продажи по кассирам"))
_COLUMN_WIDTHS = {"movie": 230, "hall": 110, "date": 100, "time": 70, "cashier": 230}


class ReportsFrame(ttk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        first_of_month = clock.now().date().replace(day=1)
        self.from_var, self.to_var = tk.StringVar(value=format_date_ru(first_of_month)), tk.StringVar(value=today_ru())
        self.upcoming_var = tk.BooleanVar(value=False)
        self.summary_var, self.error_var = tk.StringVar(), tk.StringVar()
        self._report = None
        self._build_ui()
        self.generate()

    def _build_ui(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Отчёт:").pack(side="left", padx=(0, 4))
        self.type_combo = Combo(bar, REPORT_TYPES, width=20)
        self.type_combo.set_value("revenue")
        self.type_combo.pack(side="left", padx=(0, 10))
        for label, var in (("Период с", self.from_var), ("по", self.to_var)):
            ttk.Label(bar, text=label).pack(side="left", padx=(0, 4))
            entry = ttk.Entry(bar, textvariable=var, width=12, justify="center")
            entry.pack(side="left", padx=(0, 10))
            entry.bind("<Return>", lambda event: self.generate())
        ttk.Checkbutton(bar, text="будущие сеансы",
                        variable=self.upcoming_var).pack(side="left", padx=(0, 10))
        ttk.Button(bar, text="Сформировать", command=self.generate).pack(side="left")

        presets = ttk.Frame(self)
        presets.pack(fill="x", pady=(0, 6))
        ttk.Label(presets, text="Быстрый выбор периода:", style="Muted.TLabel").pack(side="left", padx=(0, 6))
        for text, days in (("Сегодня", 1), ("7 дней", 7), ("30 дней", 30)):
            ttk.Button(presets, text=text, command=lambda d=days: self.set_period(d)).pack(side="left", padx=(0, 4))
        ttk.Button(presets, text="Этот месяц", command=self.set_month).pack(side="left")

        ttk.Label(self, textvariable=self.error_var, foreground=ERROR_COLOR).pack(anchor="w")
        ttk.Label(self, textvariable=self.summary_var, style="Header.TLabel").pack(anchor="w", pady=(0, 8))

        view_bar = ttk.Frame(self)
        view_bar.pack(fill="x", pady=(0, 6))
        ttk.Label(view_bar, text="Разрез:").pack(side="left", padx=(0, 4))
        self.table_combo = Combo(view_bar, [], width=16, on_change=self._show_table)
        self.table_combo.pack(side="left")
        ttk.Button(view_bar, text="Экспорт в CSV…", command=self.export).pack(side="left", padx=10)

        self.table = DataTable(self, (("stub", "", 100),), height=16)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, text="Выручка считается по кассовому методу: продажи — в день покупки билета, "
                             "возвраты — в день возврата.", foreground=MUTED_COLOR).pack(anchor="w", pady=(6, 0))

    def set_period(self, days):
        """Период «последние N дней» (включая сегодня) и сразу формирование отчёта."""
        today = clock.now().date()
        self.from_var.set(format_date_ru(today - timedelta(days=days - 1)))
        self.to_var.set(format_date_ru(today))
        self.generate()

    def set_month(self):
        today = clock.now().date()
        self.from_var.set(format_date_ru(today.replace(day=1)))
        self.to_var.set(format_date_ru(today))
        self.generate()

    def generate(self):
        try:
            date_from = normalize_date_input(self.from_var.get())
            date_to = normalize_date_input(self.to_var.get())
        except ServiceError as exc:
            self.error_var.set(str(exc))
            return
        self.from_var.set(date_from)
        self.to_var.set(date_to)
        self.error_var.set("")   # старая подсказка не должна висеть рядом с новым результатом или предупреждением
        kind = self.type_combo.value()
        if kind == "revenue":
            ok, report = guarded(self, report_service.revenue_report, self.user, date_from, date_to)
        elif kind == "cashiers":
            ok, report = guarded(self, report_service.cashier_report, self.user, date_from, date_to)
        else:
            ok, report = guarded(self, report_service.attendance_report, self.user, date_from, date_to,
                                 include_upcoming=bool(self.upcoming_var.get()))
        if not ok:
            return
        same_type = self._report is not None and self._report["type"] == report["type"]
        self._report = report
        self.summary_var.set(summary_text(report))
        # тот же тип отчёта — сохраняем выбранный разрез; другой тип — начинаем с первой таблицы
        self.table_combo.set_options([(name, spec["title"]) for name, spec in report["tables"].items()],
                                     keep_value=same_type)
        self._show_table()

    def _show_table(self):
        if self._report is None:
            return
        tables = self._report["tables"]
        name = self.table_combo.value() or next(iter(tables))
        spec = tables[name]
        keys = [key for key, _ in spec["columns"]]
        self.table.set_columns([(key, title, _COLUMN_WIDTHS.get(key, 120)) for key, title in spec["columns"]])
        rows = [(f"r{i}", [format_report_cell(k, row.get(k)) for k in keys], None)
                for i, row in enumerate(spec["rows"])]
        if spec["totals"]:
            rows.append(("totals", [format_report_cell(k, spec["totals"].get(k)) for k in keys], "totals"))
        self.table.set_rows(rows)

    def export(self):
        if self._report is None:
            messagebox.showinfo("Экспорт", "Сначала сформируйте отчёт.", parent=self)
            return
        name = self.table_combo.value() or next(iter(self._report["tables"]))
        period = self._report["period"]
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv", filetypes=(("CSV (открывается в Excel)", "*.csv"),),
            initialfile=f"{self._report['type']}_{name}_{period['date_from']}_{period['date_to']}.csv")
        if not path:
            return
        ok, _ = guarded(self, report_service.save_report_csv, self.user, self._report, path, name)
        if ok:
            messagebox.showinfo("Экспорт", f"Файл сохранён:\n{path}", parent=self)
