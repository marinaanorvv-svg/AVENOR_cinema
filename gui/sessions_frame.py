"""Управление сеансами и расписанием (администратор)."""
import tkinter as tk
from tkinter import messagebox, ttk

from services import admin_service, hall_service, movie_service, session_service
from services.errors import ServiceError

from .common import ERROR_COLOR, ask_confirm, guarded
from .formatting import (date_ru_from_iso, format_price, normalize_date_input, price_input,
                         session_tag, shift_date, time_range, today_ru)
from .forms import Field, FormDialog
from .widgets import Combo, DataTable, selected_int


def open_auto_schedule(parent, user, movies, movie_id=None, on_saved=None):
    """Окно «Расставить сеансы автоматически»: администратор выбирает фильм и срок, остальное программа делает сама."""
    fields = [
        Field("movie_id", "Фильм", "combo", options=tuple((m["id"], m["title"]) for m in movies), value=movie_id),
        Field("date_from", "С какой даты", value=today_ru(), hint="ДД.ММ.ГГГГ"),
        Field("days", "На сколько дней", value="7"),
        Field("per_day", "Сеансов в день", value="2", hint="Время и зал выбираются автоматически, без пересечений"),
        Field("price", "Цена билета, ₽", value="350"),
    ]

    def submit(values):
        result = session_service.auto_schedule(user, values["movie_id"], values["date_from"], values["days"],
                                               values["per_day"], values["price"])
        messagebox.showinfo("Расписание готово", f"Добавлено сеансов: {result['created']}."
                            + (f"\nНе нашлось свободного времени для: {result['skipped']}." if result["skipped"] else ""),
                            parent=parent)
    FormDialog(parent, "Сеансы автоматически", fields, on_submit=submit, on_saved=on_saved, submit_text="Расставить")


class SessionsFrame(ttk.Frame):
    COLUMNS = (("date", "Дата", 90), ("time", "Время", 130), ("movie", "Фильм", 200),
               ("hall", "Зал", 90), ("price", "Цена", 80), ("sold", "Продано", 90), ("state", "Статус", 90))

    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.from_var, self.to_var = tk.StringVar(value=today_ru()), tk.StringVar(value=shift_date(today_ru(), 30))
        self.error_var = tk.StringVar()
        self.cancelled_var = tk.BooleanVar(value=False)
        self._sessions = {}
        self._build_ui()
        self._load_filters()
        self.load()

    def _build_ui(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        for label, var in (("Период с", self.from_var), ("по", self.to_var)):
            ttk.Label(bar, text=label).pack(side="left", padx=(0, 4))
            entry = ttk.Entry(bar, textvariable=var, width=12, justify="center")
            entry.pack(side="left", padx=(0, 10))
            entry.bind("<Return>", lambda event: self.load())
        ttk.Label(bar, text="Фильм").pack(side="left", padx=(0, 4))
        self.movie_filter = Combo(bar, [(None, "Все")], width=13, on_change=self.load)
        self.movie_filter.set_value(None)
        self.movie_filter.pack(side="left", padx=(0, 8))
        ttk.Label(bar, text="Зал").pack(side="left", padx=(0, 4))
        self.hall_filter = Combo(bar, [(None, "Все")], width=9, on_change=self.load)
        self.hall_filter.set_value(None)
        self.hall_filter.pack(side="left", padx=(0, 8))
        ttk.Button(bar, text="Показать", command=self.load).pack(side="left")
        ttk.Checkbutton(bar, text="отменённые", variable=self.cancelled_var, command=self.load).pack(side="left", padx=8)
        ttk.Label(self, textvariable=self.error_var, foreground=ERROR_COLOR).pack(anchor="w")

        self.table = DataTable(self, self.COLUMNS, height=16, on_activate=self._edit_session)
        self.table.pack(fill="both", expand=True)
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Расставить автоматически", command=self._auto).pack(side="left")
        ttk.Button(buttons, text="Добавить сеанс", command=self._add_session).pack(side="left", padx=4)
        ttk.Button(buttons, text="Изменить", command=self._edit_session).pack(side="left")
        ttk.Button(buttons, text="Отменить сеанс", command=self._cancel_session).pack(side="left", padx=4)
        ttk.Button(buttons, text="Удалить", command=self._delete_session).pack(side="left")

    def load(self):
        try:
            self.from_var.set(normalize_date_input(self.from_var.get()))
            self.to_var.set(normalize_date_input(self.to_var.get()))
        except ServiceError as exc:
            self.error_var.set(str(exc))
            return
        ok, sessions = guarded(self, admin_service.list_sessions, self.user,
                               date_from=self.from_var.get(), date_to=self.to_var.get(),
                               hall_id=self.hall_filter.value(), movie_id=self.movie_filter.value(),
                               include_cancelled=bool(self.cancelled_var.get()))
        if not ok:
            return
        self.error_var.set("")
        self._sessions = {s["id"]: s for s in sessions}
        self.table.set_rows(
            (s["id"], (date_ru_from_iso(s["session_date"]), time_range(s), s["movie_title"], s["hall_name"],
                       format_price(s["price"]), f"{s['seats_sold']} из {s['seats_total']}", self._state(s)),
             "past" if s["cancelled"] or session_tag(s) == "past" else None)
            for s in sessions)

    @staticmethod
    def _state(s):
        if s["cancelled"]:
            return "Отменён"
        return "Прошёл" if s["started"] else "Ожидается"

    def _load_filters(self):
        ok_m, movies = guarded(self, movie_service.list_movies, self.user)
        ok_h, halls = guarded(self, hall_service.list_halls, self.user)
        if ok_m:
            self.movie_filter.set_options([(None, "Все")] + [(m["id"], m["title"]) for m in movies])
            self.movie_filter.set_value(None)
        if ok_h:
            self.hall_filter.set_options([(None, "Все")] + [(h["id"], h["name"]) for h in halls])
            self.hall_filter.set_value(None)

    # ------------------------------------------------------------------ формы
    def _load_refs(self):
        """Фильмы и залы для выпадающих списков; None, если справочники пусты."""
        ok_m, movies = guarded(self, movie_service.list_movies, self.user)
        ok_h, halls = guarded(self, hall_service.list_halls, self.user)
        if not (ok_m and ok_h):
            return None
        if not movies or not halls:
            messagebox.showinfo("Нет данных", "Сначала добавьте хотя бы один фильм и один зал.", parent=self)
            return None
        return movies, halls

    def _fields(self, movies, halls, session=None):
        return [
            Field("movie_id", "Фильм", "combo", options=tuple((m["id"], m["title"]) for m in movies),
                  value=session["movie_id"] if session else None),
            Field("hall_id", "Зал", "combo", options=tuple((h["id"], h["name"]) for h in halls),
                  value=session["hall_id"] if session else None),
            Field("session_date", "Дата",
                  value=date_ru_from_iso(session["session_date"]) if session else self.from_var.get(),
                  hint="ДД.ММ.ГГГГ"),
            Field("session_time", "Время начала", value=session["session_time"] if session else "18:00",
                  hint="ЧЧ:ММ"),
            Field("price", "Цена билета, ₽", value=price_input(session["price"]) if session else ""),
        ]

    def _auto(self):
        refs = self._load_refs()
        if refs is not None:
            open_auto_schedule(self, self.user, refs[0], on_saved=self.load)

    def _add_session(self):
        refs = self._load_refs()
        if refs is None:
            return
        FormDialog(
            self, "Новый сеанс", self._fields(*refs),
            on_submit=lambda v: session_service.create_session(
                self.user, v["movie_id"], v["hall_id"], v["session_date"], v["session_time"], v["price"]),
            on_saved=self.load)

    def _edit_session(self):
        session_id = selected_int(self, self.table, "Выберите сеанс в таблице.")
        if session_id is None:
            return
        refs = self._load_refs()
        if refs is None:
            return
        FormDialog(
            self, "Изменить сеанс", self._fields(*refs, session=self._sessions[session_id]),
            on_submit=lambda v: session_service.update_session(self.user, session_id, **v),
            on_saved=self.load)

    def _delete_session(self):
        session_id = selected_int(self, self.table, "Выберите сеанс в таблице.")
        if session_id is None:
            return
        s = self._sessions[session_id]
        if ask_confirm(self, f"Удалить сеанс «{s['movie_title']}» "
                             f"{date_ru_from_iso(s['session_date'])} {s['session_time']}?"):
            ok, _ = guarded(self, session_service.delete_session, self.user, session_id)
            if ok:
                self.load()

    def _cancel_session(self):
        session_id = selected_int(self, self.table, "Выберите сеанс в таблице.")
        if session_id is None:
            return
        s = self._sessions[session_id]
        sold = s["seats_sold"]
        question = (f"Отменить сеанс «{s['movie_title']}» {date_ru_from_iso(s['session_date'])} {s['session_time']}?\n"
                    + (f"Будут возвращены все проданные билеты: {sold} шт. на {format_price(s['price'] * sold)}."
                       if sold else "Проданных билетов нет."))
        if not ask_confirm(self, question):
            return
        ok, result = guarded(self, admin_service.cancel_session, self.user, session_id)
        if ok:
            messagebox.showinfo("Сеанс отменён", f"Возвращено билетов: {result['refunded']} "
                                f"на {format_price(result['amount'])}.", parent=self)
        self.load()
