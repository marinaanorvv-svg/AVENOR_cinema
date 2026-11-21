"""Небольшие модальные диалоги."""
import tkinter as tk
from tkinter import messagebox, ttk

from services import auth_service
from services.errors import ServiceError

from .common import ERROR_COLOR, center_on_parent, report_exception


class ChangePasswordDialog(tk.Toplevel):
    """Смена собственного пароля (доступна любой роли)."""

    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.old_var, self.new_var = tk.StringVar(), tk.StringVar()
        self.repeat_var, self.error_var = tk.StringVar(), tk.StringVar()
        self.title("Смена пароля")
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self._build_ui()
        center_on_parent(self, parent, 380, 270)
        self.bind("<Return>", lambda event: self._save())
        self.bind("<Escape>", lambda event: self.destroy())
        self.wait_visibility()   # без этого grab_set на Linux падает: «window not viewable»
        self.grab_set()          # модальность: пока диалог открыт, главное окно недоступно
        self.old_entry.focus_set()

    def _build_ui(self):
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        fields = (("Текущий пароль:", self.old_var), ("Новый пароль:", self.new_var),
                  ("Повторите новый:", self.repeat_var))
        for row, (label, var) in enumerate(fields):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=6)
            entry = ttk.Entry(body, textvariable=var, show="•", width=24)
            entry.grid(row=row, column=1, pady=6)
            if row == 0:
                self.old_entry = entry
        ttk.Label(body, textvariable=self.error_var, foreground=ERROR_COLOR,
                  wraplength=320).grid(row=3, column=0, columnspan=2, pady=(4, 8))
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2)
        ttk.Button(buttons, text="Сохранить", command=self._save).pack(side="left", padx=6)
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=6)

    def _save(self):
        if self.new_var.get() != self.repeat_var.get():
            self.error_var.set("Новый пароль и повтор не совпадают.")
            return
        try:
            auth_service.change_own_password(self.user, self.old_var.get(), self.new_var.get())
        except ServiceError as exc:
            self.error_var.set(str(exc))
            return
        except Exception as exc:   # баг, а не ошибка пользователя
            report_exception(self, exc)
            return
        messagebox.showinfo("Готово", "Пароль изменён.", parent=self)
        self.destroy()
