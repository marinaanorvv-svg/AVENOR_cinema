"""Универсальная форма-диалог: экраны описывают поля, а не рисуют окна вручную."""
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, ttk

from services.errors import ServiceError

from .common import ERROR_COLOR, MUTED_COLOR, center_on_parent, report_exception
from .widgets import Combo


@dataclass
class Field:
    key: str
    label: str
    kind: str = "entry"        # entry | password | combo | text | file
    options: tuple = ()        # для combo: ((значение, подпись), ...)
    value: object = ""         # начальное значение (для combo — значение, а не подпись)
    hint: str = ""             # серая подсказка под полем
    filetypes: tuple = ()      # для file: (("Изображения", "*.png *.gif"), ...)


class FormDialog(tk.Toplevel):
    """Модальная форма. on_submit(values: dict) вызывается по «Сохранить» и должен
    бросить ServiceError при неверных данных — текст ошибки покажется в форме,
    а окно останется открытым. При успехе окно закрывается и вызывается on_saved()."""

    def __init__(self, parent, title, fields, on_submit, on_saved=None, submit_text="Сохранить", width=480):
        super().__init__(parent)
        self.fields = list(fields)
        self.on_submit, self.on_saved = on_submit, on_saved
        self.inputs = {}           # ключ поля -> StringVar | Combo | Text
        self.error_var = tk.StringVar()
        self.title(title)
        self.resizable(False, False)
        self.transient(parent.winfo_toplevel())
        self._build_ui(submit_text)
        center_on_parent(self, parent, width)
        self.bind("<Escape>", lambda event: self.destroy())
        self.wait_visibility()     # без этого grab_set на Linux падает: «window not viewable»
        self.grab_set()            # модальность
        self.first_focus.focus_set()

    # ------------------------------------------------------------------ построение
    def _build_ui(self, submit_text):
        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        self.first_focus = self
        row = 0
        for field in self.fields:
            ttk.Label(body, text=field.label).grid(row=row, column=0, sticky="ne", padx=(0, 8), pady=5)
            widget = self._make_input(body, field)
            widget.grid(row=row, column=1, sticky="ew", pady=5)
            if self.first_focus is self:
                self.first_focus = widget
            row += 1
            if field.hint:
                ttk.Label(body, text=field.hint, foreground=MUTED_COLOR, wraplength=300).grid(
                    row=row, column=1, sticky="w")
                row += 1
        ttk.Label(body, textvariable=self.error_var, foreground=ERROR_COLOR, wraplength=420,
                  justify="left").grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 4))
        buttons = ttk.Frame(body)
        buttons.grid(row=row + 1, column=0, columnspan=2, pady=(6, 0))
        ttk.Button(buttons, text=submit_text, command=self._submit).pack(side="left", padx=6)
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=6)

    def _make_input(self, body, field):
        if field.kind == "combo":
            combo = Combo(body, field.options, width=32)
            self.inputs[field.key] = combo
            if any(v == field.value for v, _ in field.options):
                combo.set_value(field.value)
            elif field.options:
                combo.set(field.options[0][1])
            return combo
        if field.kind == "text":
            text = tk.Text(body, width=36, height=5, wrap="word")
            text.insert("1.0", str(field.value or ""))
            self.inputs[field.key] = text
            return text
        var = tk.StringVar(value="" if field.value is None else str(field.value))
        self.inputs[field.key] = var
        if field.kind == "file":
            holder = ttk.Frame(body)
            entry = ttk.Entry(holder, textvariable=var, width=26)
            entry.pack(side="left", fill="x", expand=True)
            ttk.Button(holder, text="Обзор…", command=lambda: self._browse(var, field)).pack(side="left", padx=(6, 0))
            return holder
        entry = ttk.Entry(body, textvariable=var, width=34, show="•" if field.kind == "password" else "")
        entry.bind("<Return>", lambda event: self._submit())
        return entry

    def _browse(self, var, field):
        path = filedialog.askopenfilename(parent=self, filetypes=field.filetypes or (("Все файлы", "*.*"),))
        if path:
            var.set(path)

    # ------------------------------------------------------------------ значения
    def get_values(self) -> dict:
        values = {}
        for field in self.fields:
            widget = self.inputs[field.key]
            if field.kind == "combo":
                values[field.key] = widget.value()
            elif field.kind == "text":
                values[field.key] = widget.get("1.0", "end").strip()
            else:
                values[field.key] = widget.get()
        return values

    def set_value(self, key, value) -> None:
        field = next(f for f in self.fields if f.key == key)
        widget = self.inputs[key]
        if field.kind == "combo":
            widget.set_value(value)
        elif field.kind == "text":
            widget.delete("1.0", "end")
            widget.insert("1.0", str(value))
        else:
            widget.set(str(value))

    def _submit(self):
        try:
            self.on_submit(self.get_values())
        except ServiceError as exc:
            self.error_var.set(str(exc))   # ошибка ввода: остаёмся в форме
            return
        except Exception as exc:           # баг: журнал + сообщение
            report_exception(self, exc)
            return
        self.destroy()
        if self.on_saved:
            self.on_saved()
