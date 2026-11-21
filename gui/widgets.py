"""Повторно используемые виджеты: таблица и выпадающий список со значениями."""
import tkinter as tk
from tkinter import messagebox, ttk

from .common import ERROR_COLOR, MUTED_COLOR


class DataTable(ttk.Frame):
    """Таблица (Treeview + прокрутка). columns: [(ключ, заголовок, ширина), ...]."""

    def __init__(self, parent, columns, height=12, on_select=None, on_activate=None):
        super().__init__(parent)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings",
                                 selectmode="browse", height=height)
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.tag_configure("past", foreground=MUTED_COLOR)
        self.tree.tag_configure("returned", foreground=MUTED_COLOR)
        self.tree.tag_configure("blocked", foreground=MUTED_COLOR)
        self.tree.tag_configure("soldout", foreground=ERROR_COLOR)
        self.tree.tag_configure("totals", background="#2a1550")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda event: on_select())
        if on_activate:
            self.tree.bind("<Double-1>", lambda event: on_activate())

    def set_columns(self, columns) -> None:
        """Меняет набор колонок (для отчётов, где таблицы разные)."""
        self.tree.delete(*self.tree.get_children())
        self.tree.configure(columns=[c[0] for c in columns])
        for key, title, width in columns:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")

    def set_rows(self, rows) -> None:
        """rows — итерируемое из (id строки, значения колонок, тег или None)."""
        self.tree.delete(*self.tree.get_children())
        for iid, values, tag in rows:
            self.tree.insert("", "end", iid=str(iid), values=tuple(values), tags=(tag,) if tag else ())

    def selected_id(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def select(self, iid) -> None:
        if str(iid) in self.tree.get_children():
            self.tree.selection_set(str(iid))


class Combo(ttk.Combobox):
    """Выпадающий список: пользователь видит подписи, программа получает значения.

    options: [(значение, подпись), ...]. value() -> значение выбранной подписи или None.
    """

    def __init__(self, parent, options, width=30, on_change=None):
        self._choices = list(options)   # не _options: так называется внутренний метод tkinter!
        super().__init__(parent, values=[label for _, label in self._choices],
                         state="readonly", width=width)
        if on_change:
            self.bind("<<ComboboxSelected>>", lambda event: on_change())

    def value(self):
        text = self.get()
        return next((value for value, label in self._choices if label == text), None)

    def set_value(self, value) -> None:
        for candidate, label in self._choices:
            if candidate == value:
                self.set(label)
                return

    def set_options(self, options, keep_value=True) -> None:
        previous = self.value()
        self._choices = list(options)
        self.configure(values=[label for _, label in self._choices])
        self.set("")
        if keep_value and any(v == previous for v, _ in self._choices):
            self.set_value(previous)
        elif self._choices:
            self.set(self._choices[0][1])


def selected_int(parent, table, message="Выберите строку в таблице.") -> int | None:
    """id выбранной строки или None (с подсказкой пользователю)."""
    iid = table.selected_id()
    if iid is None:
        messagebox.showinfo("Выбор", message, parent=parent)
        return None
    return int(iid)
