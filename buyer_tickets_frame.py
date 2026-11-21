"""«Мои билеты» покупателя: карточки билетов по группам (предстоящие, прошедшие, возвращённые), электронный билет, возврат."""
import tkinter as tk
from tkinter import messagebox

from services import buyer_service, movie_service

from . import neon
from . import palette as P
from . import theme
from .buyer_dialogs import ETicketDialog
from .common import MUTED_COLOR, ask_confirm, guarded
from .formatting import date_ru_from_iso, datetime_ru, format_price

CARD_W, CARD_H, GAP = 360, 124, 14
STATUS_TITLES = {"upcoming": "Предстоит", "past": "Просмотрен", "returned": "Возвращён"}
EMPTY_TEXT = {"upcoming": "У вас нет предстоящих сеансов. Выберите фильм в афише.",
              "past": "Прошедших сеансов пока нет.", "returned": "Возвращённых билетов нет."}


class BuyerTicketsFrame(tk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent, bg=P.PANEL)
        self.user = user
        self.navigate = None
        self.group = "upcoming"
        self.info_var = tk.StringVar()
        self._tickets, self._selected, self._images = [], None, []
        self._build_ui()
        self.load()

    def _build_ui(self):
        head = tk.Frame(self, bg=P.PANEL)
        head.pack(fill="x")
        tk.Label(head, text="Мои билеты", font=theme.font("title"), fg=P.TEXT, bg=P.PANEL).pack(side="left")
        tk.Label(head, textvariable=self.info_var, font=theme.font("small"), fg=P.MUTED, bg=P.PANEL).pack(side="left", padx=14)
        self.tabs = tk.Frame(self, bg=P.PANEL)
        self.tabs.pack(fill="x", pady=(8, 0))
        self._build_tabs()
        bottom = tk.Frame(self, bg=P.PANEL)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))
        self.show_button = neon.NeonButton(bottom, "Открыть билет", self.show_ticket, style="primary", height=38, bg=P.PANEL)
        self.show_button.pack(side="left")
        self.refund_button = neon.NeonButton(bottom, "Оформить возврат", self.refund, style="ghost", height=38, bg=P.PANEL)
        self.refund_button.pack(side="left", padx=8)
        tk.Label(bottom, text="Возврат возможен до начала сеанса.", font=theme.font("small"), fg=P.MUTED,
                 bg=P.PANEL).pack(side="left", padx=8)
        wall = tk.Frame(self, bg=P.PANEL)
        wall.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas = tk.Canvas(wall, bg=P.PANEL, bd=0, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda event: self._draw())
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _build_tabs(self):
        """Вкладки групп; выбранная выделена. При переключении пересоздаются: у кнопки стиль задаётся при создании."""
        for child in self.tabs.winfo_children():
            child.destroy()
        for key, title in buyer_service.TICKET_GROUPS:
            neon.NeonButton(self.tabs, title, lambda k=key: self.set_group(k),
                            style="primary" if key == self.group else "ghost", height=36,
                            bg=P.PANEL).pack(side="left", padx=(0, 8))

    # ------------------------------------------------------------------ данные
    def set_group(self, group):
        self.group, self._selected = group, None
        self._build_tabs()
        self.load()

    def load(self):
        ok, tickets = guarded(self, buyer_service.my_tickets, self.user, self.group)
        if not ok:
            return
        self._tickets = tickets
        if self._selected not in {t["id"] for t in tickets}:
            self._selected = None
        self.info_var.set(f"Билетов: {len(tickets)}")
        self._draw()
        self._update_buttons()

    def _selected_ticket(self):
        return next((t for t in self._tickets if t["id"] == self._selected), None)

    def _update_buttons(self):
        t = self._selected_ticket()
        self.show_button.set_enabled(t is not None)
        self.refund_button.set_enabled(bool(t and t["group"] == "upcoming"))

    # ------------------------------------------------------------------ карточки
    def _draw(self):
        c = self.canvas
        c.delete("all")
        self._images = []
        width = max(c.winfo_width(), CARD_W + 2 * GAP)
        view_h = c.winfo_height()
        columns = max(1, (width - GAP) // (CARD_W + GAP))
        left = max(GAP, (width - columns * (CARD_W + GAP) + GAP) // 2)
        for index, t in enumerate(self._tickets):
            row, col = divmod(index, columns)
            self._draw_card(left + col * (CARD_W + GAP), GAP + row * (CARD_H + GAP), t)
        rows = (len(self._tickets) + columns - 1) // columns
        full_h = max(GAP + rows * (CARD_H + GAP), view_h)
        if not self._tickets:
            c.create_text(width // 2, max(view_h, 160) // 2, text=EMPTY_TEXT[self.group], fill=P.MUTED,
                          font=theme.font("h2"), width=width - 4 * GAP, justify="center")
        c.configure(scrollregion=(0, 0, width, full_h))
        neon.draw_stars(c, width, full_h, 50 + full_h // 14)

    def _draw_card(self, x, y, t):
        c, tag = self.canvas, f"ticket{t['id']}"
        selected = t["id"] == self._selected
        c.create_polygon(P.rounded_points(x, y, x + CARD_W, y + CARD_H, 16), smooth=True,
                         fill=P.VIOLET if selected else P.PANEL_ALT, outline=P.ACCENT if selected else P.LINE,
                         width=2 if selected else 1, tags=(tag,))
        thumb = neon.poster_thumb(movie_service.poster_file(t.get("poster_path")), t.get("movie_id") or 0)
        if thumb is not None:
            self._images.append(thumb)
            c.create_image(x + 12, y + 10, image=thumb, anchor="nw", tags=(tag,))
        tx = x + 100
        c.create_text(tx, y + 12, text=t["movie_title"], anchor="nw", fill=P.TEXT, width=CARD_W - 112,
                      font=theme.font("nav_bold"), tags=(tag,))
        c.create_text(tx, y + 38, text=f"{date_ru_from_iso(t['session_date'])} · {t['session_time']} · {t['hall_name']}",
                      anchor="nw", fill=P.ACCENT_SOFT, width=CARD_W - 112, font=theme.font("small"), tags=(tag,))
        c.create_text(tx, y + 58, text=t["seat_label"], anchor="nw", fill=P.TEXT, font=theme.font("small"), tags=(tag,))
        c.create_text(tx, y + 78, text=f"Билет № {t['id']} · {format_price(t['price'])}", anchor="nw", fill=P.MUTED,
                      font=theme.font("small"), tags=(tag,))
        c.create_text(tx, y + 98, text=f"{STATUS_TITLES[t['group']]} · куплен {datetime_ru(t['purchase_date'])}", anchor="nw",
                      fill=P.ERROR if t["group"] == "returned" else P.MUTED, font=theme.font("small"), tags=(tag,))
        c.tag_bind(tag, "<Button-1>", lambda event, tid=t["id"]: self.select(tid))
        c.tag_bind(tag, "<Double-Button-1>", lambda event, tid=t["id"]: (self.select(tid), self.show_ticket()))

    def select(self, ticket_id):
        self._selected = ticket_id
        self._draw()
        self._update_buttons()

    # ------------------------------------------------------------------ действия
    def show_ticket(self):
        t = self._selected_ticket()
        if t is None:
            messagebox.showinfo("Выбор", "Выберите билет.", parent=self)
            return
        ETicketDialog(self, [t])

    def refund(self):
        t = self._selected_ticket()
        if t is None:
            messagebox.showinfo("Выбор", "Выберите билет.", parent=self)
            return
        ok, check = guarded(self, buyer_service.refund_check, self.user, t["id"])
        if not ok:
            self.load()
            return
        if not check["can_refund"]:
            messagebox.showwarning("Возврат невозможен", check["reason"], parent=self)
            self.load()
            return
        if not ask_confirm(self, f"Оформить возврат билета № {t['id']}?\n{t['movie_title']}, "
                                 f"{date_ru_from_iso(t['session_date'])} {t['session_time']}, {t['seat_label']}\n"
                                 f"Сумма к возврату: {format_price(t['price'])}"):
            return
        ok, result = guarded(self, buyer_service.refund, self.user, t["id"])
        if ok:
            messagebox.showinfo("Возврат оформлен", f"Билет № {result['id']} возвращён, место освобождено.\n"
                                f"Сумма к возврату: {format_price(result['price'])}.", parent=self)
        self._selected = None
        self.load()

    # ------------------------------------------------------------------ прокрутка колёсиком
    def _bind_wheel(self, event=None):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(sequence, self._on_wheel)

    def _unbind_wheel(self, event=None):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(sequence)

    def _on_wheel(self, event):
        if getattr(event, "num", None) == 4:
            units = -1
        elif getattr(event, "num", None) == 5:
            units = 1
        else:
            units = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        self.canvas.yview_scroll(units, "units")
