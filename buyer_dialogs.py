"""Окна покупателя: оформление заказа с тестовой оплатой и электронный билет."""
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from services import buyer_service, eticket, movie_service, ticket_print
from services.errors import ServiceError

from . import neon
from . import palette as P
from . import theme
from .common import ERROR_COLOR, MUTED_COLOR, center_on_parent, guarded
from .formatting import (bind_format, date_ru_from_iso, format_card_number, format_cvc, format_expiry,
                         format_holder, format_price)

TICKET_W, TICKET_H = 640, 330


class CheckoutDialog(tk.Toplevel):
    """Страница оформления заказа: фильм, постер, сеанс, места, стоимость и форма тестовой оплаты картой.

    on_confirm(card) выполняет покупку и возвращает True/False; окно закрывается до вызова.
    Реальных платёжных систем нет, данные карты проверяются и нигде не сохраняются.
    """

    def __init__(self, parent, quote, movie, on_confirm):
        super().__init__(parent)
        self.quote, self.movie, self.on_confirm = quote, movie, on_confirm
        self.vars = {k: tk.StringVar() for k in ("number", "holder", "expiry", "cvc")}
        self.error_var = tk.StringVar()
        for key, formatter in (("number", format_card_number), ("holder", format_holder),
                               ("expiry", format_expiry), ("cvc", format_cvc)):
            bind_format(self.vars[key], formatter)       # пробелы, «/», заглавные буквы ставятся сами
        self.title("Оформление заказа")
        self.transient(parent.winfo_toplevel())
        s = quote["session"]
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        self.poster = tk.Canvas(body, width=150, height=210, bg=P.PANEL, bd=0, highlightthickness=0)
        self.poster.grid(row=0, column=0, rowspan=8, sticky="n", padx=(0, 16))
        image, _ = neon.poster_image(movie_service.poster_file(movie.get("poster_path")), movie["id"], "small")
        self._image = image
        if image is not None:
            self.poster.create_image(0, 0, image=image, anchor="nw")
        ttk.Label(body, text="Ваш заказ", style="Header.TLabel").grid(row=0, column=1, columnspan=2, sticky="w")
        rows = [("Фильм", s["movie_title"]), ("Дата", date_ru_from_iso(s["session_date"])), ("Начало", s["session_time"]),
                ("Зал", s["hall_name"]), ("Места", "\n".join(f"{l['label']} · {l['category']}" for l in quote["lines"])),
                ("Билетов", f"{quote['count']} × {format_price(s['price'])}")]
        for i, (caption, value) in enumerate(rows, start=1):
            ttk.Label(body, text=caption, foreground=MUTED_COLOR).grid(row=i, column=1, sticky="nw", pady=2, padx=(0, 12))
            ttk.Label(body, text=value, justify="left", wraplength=260).grid(row=i, column=2, sticky="w", pady=2)
        ttk.Label(body, text="Итого к оплате", foreground=MUTED_COLOR).grid(row=7, column=1, sticky="w", pady=(8, 2))
        ttk.Label(body, text=format_price(quote["total"]), style="Header.TLabel").grid(row=7, column=2, sticky="w", pady=(8, 2))

        pay = ttk.LabelFrame(body, text="Тестовая оплата банковской картой", padding=10)
        pay.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        fields = (("Номер карты", "number", 22, ""), ("Владелец (латиницей)", "holder", 22, ""),
                  ("Срок ММ/ГГ", "expiry", 8, ""), ("CVC", "cvc", 6, "•"))
        for i, (caption, key, width, show) in enumerate(fields):
            ttk.Label(pay, text=caption).grid(row=i // 2, column=(i % 2) * 2, sticky="e", padx=4, pady=4)
            entry = ttk.Entry(pay, textvariable=self.vars[key], width=width, show=show)
            entry.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", pady=4)
            if i == 0:
                self.first_entry = entry
        ttk.Label(pay, text="Платёж тестовый: деньги не списываются, данные карты не сохраняются. "
                            "Для проверки подойдёт номер 4242 4242 4242 4242.", foreground=MUTED_COLOR,
                  wraplength=520, justify="left").grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(body, textvariable=self.error_var, foreground=ERROR_COLOR, wraplength=520).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=10, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Button(buttons, text=f"Оплатить {format_price(quote['total'])}", command=self.confirm).pack(side="left")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=8)
        self.update_idletasks()      # размер по содержимому: ничего не обрезается справа и снизу
        center_on_parent(self, parent, max(self.winfo_reqwidth() + 24, 720),
                         max(self.winfo_reqheight() + 24, 560 + 18 * max(quote["count"] - 1, 0)))
        self.bind("<Return>", lambda event: self.confirm())
        self.wait_visibility()
        self.grab_set()
        self.first_entry.focus_set()

    def card(self) -> dict:
        return {k: v.get() for k, v in self.vars.items()}

    def confirm(self):
        card = self.card()
        try:
            buyer_service.validate_card(card["number"], card["holder"], card["expiry"], card["cvc"])
        except ServiceError as exc:
            self.error_var.set(str(exc))
            return
        self.error_var.set("")
        self.destroy()
        self.on_confirm(card)


class ETicketDialog(tk.Toplevel):
    """Электронный билет AVENOR: постер, данные билета, код проверки; несколько билетов листаются.

    «Печать / PDF» сохраняет HTML-файл и открывает его в браузере: оттуда билет печатается или сохраняется в PDF.
    """

    def __init__(self, parent, tickets):
        super().__init__(parent)
        self.tickets, self.index = list(tickets), 0
        self.counter_var = tk.StringVar()
        self.title("Электронный билет AVENOR")
        self.transient(parent.winfo_toplevel())
        self.canvas = tk.Canvas(self, width=TICKET_W, height=TICKET_H, bg=P.PANEL, bd=0, highlightthickness=0)
        self.canvas.pack(padx=16, pady=(16, 6))
        self._image = None
        nav = ttk.Frame(self)
        nav.pack(fill="x", padx=16)
        self.prev_button = ttk.Button(nav, text="◀", width=3, command=lambda: self.show(self.index - 1))
        self.prev_button.pack(side="left")
        ttk.Label(nav, textvariable=self.counter_var).pack(side="left", padx=10)
        self.next_button = ttk.Button(nav, text="▶", width=3, command=lambda: self.show(self.index + 1))
        self.next_button.pack(side="left")
        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=16, pady=12)
        ttk.Button(bottom, text="Сохранить в PDF / печать", command=self.print_tickets).pack(side="left")
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
        c.create_polygon(P.rounded_points(4, 4, TICKET_W - 4, TICKET_H - 4, 24), smooth=True, fill=P.PANEL_ALT,
                         outline=P.ACCENT, width=2)
        c.create_text(30, 32, text=ticket_print.CINEMA_NAME, anchor="w", fill=P.ACCENT_SOFT, font=theme.font("title"))
        c.create_text(TICKET_W - 30, 32, text=f"Электронный билет № {ticket['id']}", anchor="e", fill=P.TEXT,
                      font=theme.font("h2"))
        c.create_line(30, 60, TICKET_W - 30, 60, fill=P.LINE, dash=(4, 4))
        image, _ = neon.poster_image(movie_service.poster_file(ticket.get("poster_path")), ticket.get("movie_id") or 0, "small")
        self._image = image
        if image is not None:
            c.create_image(30, 76, image=image, anchor="nw")
        fields = ticket_print.ticket_lines(ticket)
        c.create_text(210, 78, text=fields[0][1], anchor="nw", fill=P.TEXT, font=theme.font("h2"), width=TICKET_W - 250)
        for i, (label, value) in enumerate(fields[1:]):
            x = 210 if i < 4 else 430
            y = 124 + (i % 4) * 36
            c.create_text(x, y, text=label, anchor="nw", fill=P.MUTED, font=theme.font("small"))
            c.create_text(x, y + 14, text=value, anchor="nw", fill=P.TEXT, font=theme.font("bold"))
        c.create_line(30, TICKET_H - 44, TICKET_W - 30, TICKET_H - 44, fill=P.LINE, dash=(4, 4))
        returned = ticket["status"] != "sold"
        c.create_text(30, TICKET_H - 24, anchor="w", fill=P.ERROR if returned else P.ACCENT_SOFT, font=theme.font("bold"),
                      text="БИЛЕТ ВОЗВРАЩЁН — НЕДЕЙСТВИТЕЛЕН" if returned
                      else f"Код проверки: {ticket_print.ticket_code(ticket)}")

    def print_tickets(self):
        default = f"ticket_{self.tickets[0]['id']}.html" if len(self.tickets) == 1 else "tickets.html"
        path = filedialog.asksaveasfilename(parent=self, title="Сохранить электронный билет", initialfile=default,
                                            defaultextension=".html", filetypes=[("HTML-страница", "*.html")])
        if not path:
            return
        ok, _ = guarded(self, eticket.save_eticket_html, path, self.tickets)
        if not ok:
            return
        try:
            webbrowser.open(Path(path).resolve().as_uri())
        except Exception:      # браузер не открылся — файл всё равно сохранён
            pass
        messagebox.showinfo("Билет сохранён", f"Файл сохранён:\n{path}\n\nВ браузере нажмите «Печать» и выберите "
                                              "принтер или «Сохранить как PDF».", parent=self)
