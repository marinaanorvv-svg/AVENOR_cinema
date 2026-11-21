"""Личный кабинет покупателя: данные профиля, редактирование, смена пароля, быстрые переходы и выход."""
import tkinter as tk
from tkinter import messagebox

from services import buyer_service

from . import neon
from . import palette as P
from . import theme
from .common import ERROR_COLOR, guarded
from .dialogs import ChangePasswordDialog
from .formatting import bind_format, datetime_ru, format_phone_input


class BuyerProfileFrame(tk.Frame):
    def __init__(self, parent, user):
        super().__init__(parent, bg=P.PANEL)
        self.user = user
        self.navigate = None
        self.logout = None       # MainFrame: выход из аккаунта
        self.vars = {k: tk.StringVar() for k in ("full_name", "phone", "email")}
        bind_format(self.vars["phone"], format_phone_input)      # +7 916 903-56-00 — пробелы и дефисы ставятся сами
        self.login_var, self.registered_var, self.stats_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self._build_ui()
        self.load()

    def _label(self, parent, text=None, font_key="body", color=P.TEXT, **options):
        return tk.Label(parent, text=text, font=theme.font(font_key), fg=color, bg=P.PANEL, **options)

    def _build_ui(self):
        self._label(self, "Личный кабинет", "title").pack(anchor="w")
        card = neon.RoundedPanel(self, fill=P.PANEL_ALT, bg=P.PANEL, pad=16, glow=False)
        card.pack(fill="x", pady=(10, 0))
        box = card.body
        for key, caption in (("full_name", "Имя и фамилия"), ("phone", "Телефон"), ("email", "Электронная почта")):
            tk.Label(box, text=caption, font=theme.font("small"), fg=P.MUTED, bg=P.PANEL_ALT).pack(anchor="w", pady=(8, 0))
            neon.NeonEntry(box, self.vars[key], width=360, height=38, bg=P.PANEL_ALT).pack(anchor="w")
        tk.Label(box, textvariable=self.login_var, font=theme.font("small"), fg=P.MUTED, bg=P.PANEL_ALT).pack(anchor="w", pady=(10, 0))
        tk.Label(box, textvariable=self.registered_var, font=theme.font("small"), fg=P.MUTED, bg=P.PANEL_ALT).pack(anchor="w")
        self.error_var = tk.StringVar()
        tk.Label(box, textvariable=self.error_var, font=theme.font("small"), fg=ERROR_COLOR, bg=P.PANEL_ALT,
                 wraplength=420, justify="left").pack(anchor="w", pady=(6, 0))
        row = tk.Frame(box, bg=P.PANEL_ALT)
        row.pack(anchor="w", pady=(8, 0))
        neon.NeonButton(row, "Сохранить данные", self.save, style="primary", height=40, bg=P.PANEL_ALT).pack(side="left")
        neon.NeonButton(row, "Сменить пароль", self.change_password, style="ghost", height=40,
                        bg=P.PANEL_ALT).pack(side="left", padx=8)
        self._label(self, textvariable=self.stats_var, font_key="small", color=P.ACCENT_SOFT).pack(anchor="w", pady=(12, 0))
        links = tk.Frame(self, bg=P.PANEL)
        links.pack(anchor="w", pady=(8, 0))
        neon.NeonButton(links, "Мои билеты", lambda: self._go("my_tickets"), style="ghost", height=38, bg=P.PANEL).pack(side="left")
        neon.NeonButton(links, "История покупок", lambda: self._go("orders"), style="ghost", height=38,
                        bg=P.PANEL).pack(side="left", padx=8)
        neon.NeonButton(links, "Выйти из аккаунта", self._logout, style="ghost", height=38, icon="logout",
                        bg=P.PANEL).pack(side="left")

    def _go(self, key):
        if self.navigate:
            self.navigate(key)

    def _logout(self):
        if self.logout:
            self.logout()

    def load(self):
        ok, profile = guarded(self, buyer_service.get_profile, self.user)
        if not ok:
            return
        self.vars["full_name"].set(profile["full_name"])
        self.vars["phone"].set(profile["phone"] or "")
        self.vars["email"].set(profile["email"] or "")
        self.login_var.set(f"Логин: {profile['username']}")
        self.registered_var.set("Дата регистрации: " + (datetime_ru(profile["created_at"]) if profile["created_at"]
                                                        else "не указана (учётная запись создана до ведения даты)"))
        ok_t, upcoming = guarded(self, buyer_service.my_tickets, self.user, "upcoming")
        ok_o, orders = guarded(self, buyer_service.list_my_orders, self.user)
        if ok_t and ok_o:
            self.stats_var.set(f"Предстоящих билетов: {len(upcoming)} · заказов: {len(orders)}")

    def save(self):
        ok, profile = guarded(self, buyer_service.update_profile, self.user, self.vars["full_name"].get(),
                              self.vars["phone"].get(), self.vars["email"].get())
        if not ok:
            return
        self.load()
        messagebox.showinfo("Готово", "Данные профиля сохранены.", parent=self)

    def change_password(self):
        ChangePasswordDialog(self, self.user)
