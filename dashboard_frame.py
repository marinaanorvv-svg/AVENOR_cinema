"""Главная панель администратора: сводка, график продаж за неделю, ближайшие сеансы и последние продажи."""
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from services import admin_service, clock

from . import palette as P
from . import theme
from .common import MUTED_COLOR, guarded
from .formatting import date_ru_from_iso, datetime_ru, format_price
from .widgets import DataTable

REFRESH_MS = 30_000   # панель сама обновляется раз в 30 секунд (и при каждом открытии)
CHART_PAD = {"left": 52, "right": 12, "top": 26, "bottom": 28}


def bar_geometry(values, width, height, pad=CHART_PAD):
    """Столбцы графика: [(x1, y1, x2, y2)] для значений values внутри холста width×height (без tkinter).

    Нулевые и отрицательные значения рисуются тонкой линией у основания, чтобы день был виден на оси.
    """
    plot_w = max(width - pad["left"] - pad["right"], 1)
    plot_h = max(height - pad["top"] - pad["bottom"], 1)
    top_value = max([v for v in values if v > 0] + [1])
    slot = plot_w / max(len(values), 1)
    bar_w = max(slot * 0.56, 2)
    base = pad["top"] + plot_h
    boxes = []
    for index, value in enumerate(values):
        x1 = pad["left"] + slot * index + (slot - bar_w) / 2
        h = plot_h * max(value, 0) / top_value
        boxes.append((x1, base - max(h, 2), x1 + bar_w, base))
    return boxes


def short_day(day_iso: str) -> str:
    """'2026-11-12' -> '12.11'."""
    return f"{day_iso[8:10]}.{day_iso[5:7]}"


class StatCard(tk.Frame):
    """Карточка с крупным числом и подписью."""

    def __init__(self, parent, caption):
        super().__init__(parent, bg=P.PANEL_ALT, highlightbackground=P.LINE, highlightthickness=1)
        self.value_var, self.note_var = tk.StringVar(value="—"), tk.StringVar()
        tk.Label(self, textvariable=self.value_var, bg=P.PANEL_ALT, fg=P.TEXT,
                 font=theme.font("h2")).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(self, text=caption, bg=P.PANEL_ALT, fg=P.ACCENT_SOFT,
                 font=theme.font("small")).pack(anchor="w", padx=12)
        tk.Label(self, textvariable=self.note_var, bg=P.PANEL_ALT, fg=P.MUTED,
                 font=theme.font("small")).pack(anchor="w", padx=12, pady=(0, 8))

    def show(self, value, note=""):
        self.value_var.set(str(value))
        self.note_var.set(note)


class DashboardFrame(ttk.Frame):
    CARDS = (("movies", "Фильмов"), ("sessions", "Действующих сеансов"), ("halls", "Кинозалов"),
             ("tickets", "Билетов сегодня"), ("revenue", "Выручка сегодня"), ("users", "Пользователей"))
    UPCOMING_COLUMNS = (("when", "Когда", 110), ("movie", "Фильм", 170), ("hall", "Зал", 70), ("sold", "Продано", 80))
    RECENT_COLUMNS = (("id", "№", 50), ("movie", "Фильм", 190), ("seat", "Место", 120), ("client", "Клиент", 140),
                      ("price", "Цена", 80), ("bought", "Куплен", 130), ("status", "Статус", 90))

    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.updated_var = tk.StringVar()
        self.cards, self._series, self._job = {}, [], None
        self._build_ui()
        self.refresh()
        self._schedule()

    # ------------------------------------------------------------------ интерфейс
    def _build_ui(self):
        head = ttk.Frame(self)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text="Главная панель", style="Header.TLabel").pack(side="left")
        ttk.Button(head, text="Обновить", command=self.refresh).pack(side="right")
        ttk.Label(head, textvariable=self.updated_var, foreground=MUTED_COLOR).pack(side="right", padx=10)

        row = tk.Frame(self, bg=P.PANEL)
        row.pack(fill="x", pady=(0, 10))
        for index, (key, caption) in enumerate(self.CARDS):
            card = StatCard(row, caption)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 6, 0))
            row.columnconfigure(index, weight=1, uniform="cards")
            self.cards[key] = card

        middle = ttk.Frame(self)
        middle.pack(fill="both", expand=True)
        chart_box = ttk.Frame(middle)
        chart_box.pack(side="left", fill="both", expand=True, padx=(0, 10))
        ttk.Label(chart_box, text="Выручка за 7 дней", style="Muted.TLabel").pack(anchor="w")
        self.chart = tk.Canvas(chart_box, height=170, bg=P.PANEL_ALT, bd=0, highlightthickness=1,
                               highlightbackground=P.LINE)
        self.chart.pack(fill="both", expand=True)
        self.chart.bind("<Configure>", lambda event: self._draw_chart())
        upcoming_box = ttk.Frame(middle)
        upcoming_box.pack(side="left", fill="both", expand=True)
        ttk.Label(upcoming_box, text="Ближайшие сеансы", style="Muted.TLabel").pack(anchor="w")
        self.upcoming_table = DataTable(upcoming_box, self.UPCOMING_COLUMNS, height=5)
        self.upcoming_table.pack(fill="both", expand=True)

        ttk.Label(self, text="Последние продажи", style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        self.recent_table = DataTable(self, self.RECENT_COLUMNS, height=5)
        self.recent_table.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ данные
    def refresh(self):
        ok, data = guarded(self, admin_service.dashboard, self.user)
        if not ok:
            return
        self.cards["movies"].show(data["movies"])
        self.cards["sessions"].show(data["active_sessions"], "ещё не закончились")
        self.cards["halls"].show(data["halls"])
        self.cards["tickets"].show(data["tickets_today"], f"возвратов: {data['returns_today']}")
        self.cards["revenue"].show(format_price(data["revenue_today"]), "продажи − возвраты")
        self.cards["users"].show(data["users"], f"покупателей: {data['viewers']}")
        self._series = data["series"]
        self._draw_chart()
        self.upcoming_table.set_rows(
            (s["id"], (f"{date_ru_from_iso(s['date'])[:5]} {s['time']}", s["movie"], s["hall"],
                       f"{s['sold']} из {s['total']}"), None) for s in data["upcoming"])
        self.recent_table.set_rows(
            (t["id"], (t["id"], t["movie"], t["seat"], t["client"], format_price(t["price"]),
                       datetime_ru(t["bought"]), "Возвращён" if t["status"] == "returned" else "Продан"),
             "returned" if t["status"] == "returned" else None) for t in data["recent_sales"])
        self.updated_var.set("Обновлено " + datetime.strptime(data["generated_at"], "%Y-%m-%d %H:%M:%S").strftime("%H:%M"))

    def _draw_chart(self):
        canvas = self.chart
        canvas.delete("all")
        if not self._series:
            return
        width, height = max(canvas.winfo_width(), 300), max(canvas.winfo_height(), 120)
        values = [d["revenue"] for d in self._series]
        boxes = bar_geometry(values, width, height)
        base = boxes[0][3]
        canvas.create_line(CHART_PAD["left"], base, width - CHART_PAD["right"], base, fill=P.LINE)
        top = max([v for v in values if v > 0] + [1])
        canvas.create_text(CHART_PAD["left"] - 6, CHART_PAD["top"], text=format_price(top), anchor="e",
                           fill=P.MUTED, font=theme.font("small"))
        canvas.create_text(CHART_PAD["left"] - 6, base, text="0", anchor="e", fill=P.MUTED, font=theme.font("small"))
        for (x1, y1, x2, y2), day in zip(boxes, self._series):
            canvas.create_rectangle(x1, y1, x2, y2, fill=P.ACCENT, outline=P.ACCENT_SOFT)
            canvas.create_text((x1 + x2) / 2, base + 14, text=short_day(day["date"]), fill=P.MUTED,
                               font=theme.font("small"))
            if day["revenue"]:
                canvas.create_text((x1 + x2) / 2, y1 - 8, text=f"{day['tickets']} бил.", fill=P.TEXT,
                                   font=theme.font("small"))

    # ------------------------------------------------------------------ автообновление
    def _schedule(self):
        self._job = self.after(REFRESH_MS, self._auto_refresh)

    def _auto_refresh(self):
        self._job = None
        self.refresh()
        self._schedule()

    def destroy(self):
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        super().destroy()
