"""Управление пользователями и сотрудниками (администратор)."""
import tkinter as tk
from tkinter import messagebox, ttk

from services import admin_service, auth_service
from services.permissions import Role

from .common import MUTED_COLOR, ask_confirm, guarded
from .formatting import role_title
from .forms import Field, FormDialog
from .widgets import Combo, DataTable, selected_int

ROLE_OPTIONS = tuple((role, role_title(role)) for role in Role.ALL)
STATUS_FILTER = ((None, "Все"), (True, "Активные"), (False, "Заблокированные"))


class UsersFrame(ttk.Frame):
    COLUMNS = (("username", "Логин", 130), ("name", "ФИО", 220), ("role", "Роль", 120), ("status", "Статус", 120))

    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.search_var, self.info_var = tk.StringVar(), tk.StringVar()
        self._users = {}
        self._build_ui()
        self.reload()

    def _build_ui(self):
        ttk.Label(self, text="Пользователи и сотрудники", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Поиск:").pack(side="left")
        entry = ttk.Entry(bar, textvariable=self.search_var, width=22)
        entry.pack(side="left", padx=(4, 10))
        entry.bind("<KeyRelease>", lambda event: self.reload())
        ttk.Label(bar, text="Роль:").pack(side="left")
        self.role_filter = Combo(bar, ((None, "Все"),) + ROLE_OPTIONS, width=14, on_change=self.reload)
        self.role_filter.set_value(None)
        self.role_filter.pack(side="left", padx=(4, 10))
        ttk.Label(bar, text="Статус:").pack(side="left")
        self.status_filter = Combo(bar, STATUS_FILTER, width=16, on_change=self.reload)
        self.status_filter.set_value(None)
        self.status_filter.pack(side="left", padx=4)
        ttk.Label(bar, textvariable=self.info_var, foreground=MUTED_COLOR).pack(side="left", padx=8)

        self.table = DataTable(self, self.COLUMNS, height=14, on_select=self._on_select, on_activate=self._edit_user)
        self.table.pack(fill="both", expand=True)
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Создать", command=self._create_user).pack(side="left")
        ttk.Button(buttons, text="Создать кассира", command=self._create_cashier).pack(side="left", padx=4)
        ttk.Button(buttons, text="Изменить", command=self._edit_user).pack(side="left")
        self.toggle_button = ttk.Button(buttons, text="Заблокировать", command=self._toggle_user)
        self.toggle_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="Сменить роль", command=self._change_role).pack(side="left")
        ttk.Button(buttons, text="Сбросить пароль", command=self._reset_password).pack(side="left", padx=4)
        ttk.Label(self, text="Свою учётную запись заблокировать или понизить нельзя; последнего администратора тоже.",
                  foreground=MUTED_COLOR).pack(anchor="w", pady=(6, 0))

    def reload(self, select=None):
        ok, users = guarded(self, admin_service.list_users, self.user, search=self.search_var.get(),
                            role=self.role_filter.value(), active=self.status_filter.value())
        if not ok:
            return
        self._users = {u["id"]: u for u in users}
        self.table.set_rows(
            (u["id"], (u["username"], u["full_name"], role_title(u["role"]),
                       "Активна" if u["is_active"] else "Заблокирована"), None if u["is_active"] else "blocked")
            for u in users)
        self.info_var.set(f"Найдено: {len(users)}")
        if select in self._users:
            self.table.select(select)
        self._on_select()

    def _on_select(self):
        iid = self.table.selected_id()
        blocked = iid is not None and int(iid) in self._users and not self._users[int(iid)]["is_active"]
        self.toggle_button.configure(text="Разблокировать" if blocked else "Заблокировать")

    def _new_user_form(self, role):
        FormDialog(
            self, "Новый сотрудник" if role == Role.CASHIER else "Новый пользователь",
            [Field("username", "Логин", hint="3–32 символа: латиница, цифры, «_» и «.»"),
             Field("password", "Пароль", "password", hint="Не менее 6 символов"),
             Field("role", "Роль", "combo", options=ROLE_OPTIONS, value=role),
             Field("full_name", "ФИО")],
            on_submit=lambda v: auth_service.create_user_account(
                self.user, v["username"], v["password"], v["role"], v["full_name"]),
            on_saved=lambda: (messagebox.showinfo("Готово", "Учётная запись создана.", parent=self), self.reload()))

    def _create_user(self):
        self._new_user_form(Role.VIEWER)

    def _create_cashier(self):
        self._new_user_form(Role.CASHIER)

    def _edit_user(self):
        user_id = selected_int(self, self.table, "Выберите пользователя в таблице.")
        if user_id is None:
            return
        target = self._users[user_id]
        FormDialog(
            self, f"Изменить: {target['username']}",
            [Field("username", "Логин", value=target["username"]), Field("full_name", "ФИО", value=target["full_name"])],
            on_submit=lambda v: admin_service.update_user_profile(self.user, user_id, v["username"], v["full_name"]),
            on_saved=lambda: self.reload(select=user_id))

    def _toggle_user(self):
        user_id = selected_int(self, self.table, "Выберите пользователя в таблице.")
        if user_id is None:
            return
        target = self._users[user_id]
        make_active = not target["is_active"]
        action = "разблокировать" if make_active else "заблокировать"
        if ask_confirm(self, f"{action.capitalize()} пользователя «{target['username']}»?"):
            guarded(self, auth_service.set_user_active, self.user, user_id, make_active)
            self.reload(select=user_id)

    def _change_role(self):
        user_id = selected_int(self, self.table, "Выберите пользователя в таблице.")
        if user_id is None:
            return
        FormDialog(
            self, f"Роль: {self._users[user_id]['username']}",
            [Field("role", "Роль", "combo", options=ROLE_OPTIONS, value=self._users[user_id]["role"])],
            on_submit=lambda v: admin_service.assign_role(self.user, user_id, v["role"]),
            on_saved=lambda: self.reload(select=user_id))

    def _reset_password(self):
        user_id = selected_int(self, self.table, "Выберите пользователя в таблице.")
        if user_id is None:
            return
        FormDialog(
            self, f"Новый пароль: {self._users[user_id]['username']}",
            [Field("password", "Новый пароль", "password", hint="Не менее 6 символов")],
            on_submit=lambda v: auth_service.reset_password(self.user, user_id, v["password"]),
            on_saved=lambda: self.reload(select=user_id))
