"""Окна рабочего места кассира: готовый билет, страница оплаты, текстовый отчёт смены."""
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from services import cashier_service, ticket_print

from . import palette as P
from . import theme
from .common import ERROR_COLOR, MUTED_COLOR, center_on_parent, guarded
from .formatting import date_ru_from_iso, format_price
from .widgets import Combo

TICKET_W, TICKET_H = 560, 300


def parse_money(text) -> float | None:
    """'1 000,50' -> 1000.5; пустая строка -> None; не число -> ValueError."""
    cleaned = (text or "").replace(" ", "").replace(" ", "").replace(",", ".").replace("₽", "")
    if not cleaned:
        return None
    value = float(cleaned)
    if value < 0:
        raise ValueError(text)
    return value


def change_text(received_text, total) -> str:
    """Подпись под полем «Получено»: сдача, недостача или подсказка."""
    try:
        received = parse_money(received_text)
    except ValueError:
        return "Введите сумму числом."
    if received is None:
        return ""
    if received + 1e-9 < total:
        return f"Не хватает {format_price(total - received)}"
    return f"Сдача: {format_price(received - total)}"


class TicketDialog(tk.Toplevel):
    """Готовый билет на экране; если билетов несколько — листаются. Кнопка «Печать / PDF» сохраняет билеты
    в HTML-файл и открывает его в браузере: оттуда билет печатается или сохраняется в PDF."""

    def __init__(self, parent, tickets):
        super().__init__(parent)
        self.tickets, self.index = list(tickets), 0
        self.counter_var = tk.StringVar()
        self.title("Билет AVENOR")
        self.transient(parent.winfo_toplevel())
        self.canvas = tk.Canvas(self, width=TICKET_W, height=TICKET_H, bg=P.PANEL, bd=0, highlightthickness=0)
        self.canvas.pack(padx=16, pady=(16, 6))
        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=16)
        self.prev_button = ttk.Button(nav, text="◀", width=3, command=lambda: self.show(self.index - 1))
        self.prev_button.pack(side="left")
        ttk.Label(nav, textvariable=self.counter_var).pack(side="left", padx=10)
        self.next_button = ttk.Button(nav, text="▶", width=3, command=lambda: self.show(self.index + 1))
        self.next_button.pack(side="left")
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=16, pady=12)
        ttk.Button(bottom, text="Печать / PDF", command=self.print_tickets).pack(side="left")
        ttk.Button(bottom, text="Закрыть", command=self.destroy).pack(side="right")
        center_on_parent(self, parent, TICKET_W + 32, TICKET_H + 120)
        self.wait_visibility()
        self.grab_set()
        self.show(0)

    def show(self, index):
        if not self.tickets:
            return
        self.index = max(0, min(index, len(self.tickets) - 1))
        self.counter_var.set(f"Билет {self.index + 1} из {len(self.tickets)}")
        self.prev_button.configure(state="normal" if self.index > 0 else "disabled")
        self.next_button.configure(state="normal" if self.index < len(self.tickets) - 1 else "disabled")
        self._draw(self.tickets[self.index])

    def _draw(self, ticket):
        c = self.canvas
        c.delete("all")
        c.create_polygon(P.rounded_points(4, 4, TICKET_W - 4, TICKET_H - 4, 22), smooth=True, fill=P.PANEL_ALT,
                         outline=P.ACCENT, width=2)
        c.create_text(30, 34, text=ticket_print.CINEMA_NAME, anchor="w", fill=P.ACCENT_SOFT, font=theme.font("title"))
        c.create_text(TICKET_W - 30, 34, text=f"Билет № {ticket['id']}", anchor="e", fill=P.TEXT, font=theme.font("h2"))
        c.create_line(30, 62, TICKET_W - 30, 62, fill=P.LINE, dash=(4, 4))
        fields = ticket_print.ticket_lines(ticket)
        c.create_text(30, 80, text=fields[0][1], anchor="nw", fill=P.TEXT, font=theme.font("h2"), width=TICKET_W - 60)
        rest = fields[1:]
        for i, (label, value) in enumerate(rest):
            x = 30 if i < 4 else 300
            y = 128 + (i % 4) * 36
            c.create_text(x, y, text=label, anchor="nw", fill=P.MUTED, font=theme.font("small"))
            c.create_text(x, y + 14, text=value, anchor="nw", fill=P.TEXT, font=theme.font("bold"))
        c.create_line(30, TICKET_H - 44, TICKET_W - 30, TICKET_H - 44, fill=P.LINE, dash=(4, 4))
        c.create_text(30, TICKET_H - 24, text=f"Код билета: {ticket_print.ticket_code(ticket)}", anchor="w",
                      fill=P.ACCENT_SOFT, font=theme.font("bold"))

    def print_tickets(self):
        default = f"ticket_{self.tickets[0]['id']}.html" if len(self.tickets) == 1 else "tickets.html"
        path = filedialog.asksaveasfilename(parent=self, title="Сохранить билет для печати", initialfile=default,
                                            defaultextension=".html", filetypes=[("HTML-страница", "*.html")])
        if not path:
            return
        ok, _ = guarded(self, ticket_print.save_tickets_html, path, self.tickets)
        if not ok:
            return
        try:
            webbrowser.open(Path(path).resolve().as_uri())
        except Exception:      # браузер не открылся — файл всё равно сохранён
            pass
        messagebox.showinfo("Билет сохранён", f"Файл сохранён:\n{path}\n\nВ браузере нажмите «Печать» "
                                              "и выберите принтер или «Сохранить как PDF».", parent=self)


class PaymentDialog(tk.Toplevel):
    """Страница подтверждения продажи: состав заказа, способ оплаты, при наличных — сдача.

    on_confirm(method) выполняет продажу и возвращает True/False; окно закрывается после вызова.
    """

    def __init__(self, parent, quote, on_confirm):
        super().__init__(parent)
        self.quote, self.on_confirm = quote, on_confirm
        self.total = float(quote["total"])
        self.received_var, self.change_var, self.error_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.title("Подтверждение продажи")
        self.transient(parent.winfo_toplevel())
        s = quote["session"]
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Оформление продажи", style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        rows = [("Фильм", s["movie_title"]), ("Дата", date_ru_from_iso(s["session_date"])),
                ("Начало", s["session_time"]), ("Зал", s["hall_name"]),
                ("Места", "\n".join(f"{l['label']} · {l['category']}" for l in quote["lines"])),
                ("Билетов", str(quote["count"])), ("Цена билета", format_price(s["price"]))]
        for i, (caption, value) in enumerate(rows, start=1):
            ttk.Label(body, text=caption, foreground=MUTED_COLOR).grid(row=i, column=0, sticky="nw", pady=2, padx=(0, 14))
            ttk.Label(body, text=value, justify="left", wraplength=300).grid(row=i, column=1, sticky="w", pady=2)
        last = len(rows) + 1
        ttk.Label(body, text="Итого к оплате", foreground=MUTED_COLOR).grid(row=last, column=0, sticky="w", pady=(10, 2))
        ttk.Label(body, text=format_price(self.total), style="Header.TLabel").grid(row=last, column=1, sticky="w", pady=(10, 2))
        ttk.Label(body, text="Способ оплаты", foreground=MUTED_COLOR).grid(row=last + 1, column=0, sticky="w", pady=4)
        self.method_combo = Combo(body, cashier_service.PAYMENT_OPTIONS, width=22, on_change=self._method_changed)
        self.method_combo.set_value("cash")
        self.method_combo.grid(row=last + 1, column=1, sticky="w")
        self.received_caption = ttk.Label(body, text="Получено, ₽", foreground=MUTED_COLOR)
        self.received_caption.grid(row=last + 2, column=0, sticky="w", pady=4)
        self.received_entry = ttk.Entry(body, textvariable=self.received_var, width=14)
        self.received_entry.grid(row=last + 2, column=1, sticky="w")
        self.received_entry.bind("<KeyRelease>", lambda event: self._update_change())
        ttk.Label(body, textvariable=self.change_var).grid(row=last + 3, column=1, sticky="w")
        ttk.Label(body, textvariable=self.error_var, foreground=ERROR_COLOR, wraplength=360).grid(
            row=last + 4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=last + 5, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(buttons, text="Подтвердить оплату", command=self.confirm).pack(side="left")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=8)
        center_on_parent(self, parent, 440, 470 + 18 * max(quote["count"] - 1, 0))
        self.wait_visibility()
        self.grab_set()

    def _method_changed(self):
        cash = self.method_combo.value() == "cash"
        state = "normal" if cash else "disabled"
        self.received_entry.configure(state=state)
        if not cash:
            self.received_var.set("")
        self._update_change()

    def _update_change(self):
        self.change_var.set(change_text(self.received_var.get(), self.total) if self.method_combo.value() == "cash" else "")

    def confirm(self):
        method = self.method_combo.value()
        if method not in dict(cashier_service.PAYMENT_OPTIONS):
            self.error_var.set("Выберите способ оплаты.")
            return
        if method == "cash":
            try:
                received = parse_money(self.received_var.get())
            except ValueError:
                self.error_var.set("Сумма «Получено» должна быть числом.")
                return
            if received is not None and received + 1e-9 < self.total:
                self.error_var.set("Полученной суммы недостаточно для оплаты.")
                return
        self.error_var.set("")
        self.destroy()
        self.on_confirm(method)


class TextReportDialog(tk.Toplevel):
    """Текстовый отчёт (итоги смены) с сохранением в файл."""

    def __init__(self, parent, title, text, filename="report.txt"):
        super().__init__(parent)
        self.text, self.filename = text, filename
        self.title(title)
        self.transient(parent.winfo_toplevel())
        box = tk.Text(self, width=62, height=min(max(text.count("\n") + 2, 8), 24), wrap="word")
        box.insert("1.0", text)
        box.configure(state="disabled")
        box.pack(padx=14, pady=(14, 8), fill="both", expand=True)
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(bottom, text="Сохранить в файл", command=self.save).pack(side="left")
        ttk.Button(bottom, text="Закрыть", command=self.destroy).pack(side="right")
        center_on_parent(self, parent, 520, 440)
        self.wait_visibility()
        self.grab_set()

    def save(self):
        path = filedialog.asksaveasfilename(parent=self, title="Сохранить отчёт", initialfile=self.filename,
                                            defaultextension=".txt", filetypes=[("Текстовый файл", "*.txt")])
        if not path:
            return
        try:
            Path(path).write_text(self.text, encoding="utf-8")
        except OSError as exc:
            messagebox.showwarning("Внимание", f"Не удалось сохранить файл: {exc.strerror or exc}.", parent=self)
            return
        messagebox.showinfo("Готово", f"Отчёт сохранён:\n{path}", parent=self)
