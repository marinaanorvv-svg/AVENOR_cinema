"""Справочник «Залы»: создание, схема мест, типы мест (администратор)."""
import tkinter as tk
from tkinter import ttk

from services import hall_service

from .common import MUTED_COLOR, ask_confirm, guarded
from .formatting import layout_of_scheme
from .forms import Field, FormDialog
from .seat_map import SeatMap
from .widgets import DataTable, selected_int

SEAT_TYPE_OPTIONS = (("regular", "Обычное"), ("vip", "VIP"))
_VIP_HINT = "Номера рядов через запятую, например: 4, 5. Можно оставить пустым."


class HallsFrame(ttk.Frame):
    COLUMNS = (("name", "Зал", 140), ("capacity", "Мест", 60))

    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.title_var = tk.StringVar(value="Выберите зал слева.")
        self._halls, self._hall_id, self._scheme = {}, None, None
        self._build_ui()
        self.reload()

    def _build_ui(self):
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(0, 14))
        self.table = DataTable(left, self.COLUMNS, height=14, on_select=self._on_select)
        self.table.pack(fill="y", expand=True)
        for text, command in (("Создать зал", self._create_hall), ("Переименовать", self._rename_hall),
                              ("Изменить схему", self._reconfigure_hall), ("Удалить зал", self._delete_hall)):
            ttk.Button(left, text=text, command=command).pack(fill="x", pady=(6, 0))

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, textvariable=self.title_var, style="Header.TLabel").pack(anchor="w", pady=(0, 10))
        self.seat_map = SeatMap(right, on_click=self._on_seat_click)
        self.seat_map.pack()
        ttk.Label(right, text="Нажмите на место, чтобы переключить его тип: обычное ⇄ VIP.",
                  foreground=MUTED_COLOR).pack(pady=(12, 4))
        ttk.Button(right, text="Тип целого ряда…", command=self._set_row_type).pack()

    # ------------------------------------------------------------------ данные
    def reload(self, select=None):
        ok, halls = guarded(self, hall_service.list_halls, self.user)
        if not ok:
            return
        self._halls = {h["id"]: h for h in halls}
        self.table.set_rows((h["id"], (h["name"], h["capacity"]), None) for h in halls)
        target = select or self._hall_id
        if target in self._halls:
            self.table.select(target)
            self._open_hall(target)
        else:
            self._open_hall(None)

    def _on_select(self):
        iid = self.table.selected_id()
        if iid is not None and int(iid) != self._hall_id:
            self._open_hall(int(iid))

    def _open_hall(self, hall_id):
        self._hall_id, self._scheme = None, None
        if hall_id is not None:
            ok, scheme = guarded(self, hall_service.get_hall_scheme, self.user, hall_id)
            if ok:
                self._hall_id, self._scheme = hall_id, scheme
        if self._scheme is None:
            self.title_var.set("Выберите зал слева.")
            self.seat_map.render([])
            return
        rows, per_row, _ = layout_of_scheme(self._scheme)
        vip = sum(1 for r in self._scheme["rows"] for seat in r["seats"] if seat["seat_type"] == "vip")
        self.title_var.set(f"{self._scheme['hall']['name']}: {rows} рядов × {per_row} мест "
                           f"(всего {self._scheme['hall']['capacity']}, из них VIP: {vip})")
        self.seat_map.render(self._scheme["rows"])

    def _need_hall(self):
        return selected_int(self, self.table, "Выберите зал в таблице.")

    # ------------------------------------------------------------------ действия
    def _on_seat_click(self, seat):
        if self._hall_id is None:
            return
        new_type = "regular" if seat["seat_type"] == "vip" else "vip"
        guarded(self, hall_service.set_seat_type, self.user, seat["id"], new_type)
        self._open_hall(self._hall_id)   # перерисовать: либо тип сменился, либо показана причина отказа

    def _layout_fields(self, rows="", per_row="", vip=""):
        return [Field("rows", "Количество рядов", value=rows, hint=f"От 1 до {hall_service.MAX_ROWS}"),
                Field("seats_per_row", "Мест в ряду", value=per_row,
                      hint=f"От 1 до {hall_service.MAX_SEATS_PER_ROW}"),
                Field("vip_rows", "VIP-ряды", value=vip, hint=_VIP_HINT)]

    def _create_hall(self):
        FormDialog(
            self, "Новый зал", [Field("name", "Название")] + self._layout_fields(),
            on_submit=lambda v: hall_service.create_hall(
                self.user, v["name"], v["rows"], v["seats_per_row"], v["vip_rows"]),
            on_saved=self.reload)

    def _rename_hall(self):
        hall_id = self._need_hall()
        if hall_id is None:
            return
        FormDialog(self, "Переименовать зал", [Field("name", "Название", value=self._halls[hall_id]["name"])],
                   on_submit=lambda v: hall_service.rename_hall(self.user, hall_id, v["name"]),
                   on_saved=lambda: self.reload(select=hall_id))

    def _reconfigure_hall(self):
        hall_id = self._need_hall()
        if hall_id is None or hall_id != self._hall_id:
            return
        rows, per_row, vip = layout_of_scheme(self._scheme)
        form = self._layout_fields(rows, per_row, ", ".join(map(str, vip)))
        form[0].hint = "Схему можно менять, пока в зале нет сеансов. Места будут созданы заново."
        FormDialog(
            self, "Изменить схему зала", form,
            on_submit=lambda v: hall_service.reconfigure_hall(
                self.user, hall_id, v["rows"], v["seats_per_row"], v["vip_rows"]),
            on_saved=lambda: self.reload(select=hall_id))

    def _set_row_type(self):
        hall_id = self._need_hall()
        if hall_id is None:
            return
        FormDialog(
            self, "Тип ряда",
            [Field("row", "Номер ряда"), Field("seat_type", "Тип мест", "combo", options=SEAT_TYPE_OPTIONS)],
            on_submit=lambda v: hall_service.set_row_type(self.user, hall_id, v["row"], v["seat_type"]),
            on_saved=lambda: self.reload(select=hall_id))

    def _delete_hall(self):
        hall_id = self._need_hall()
        if hall_id is None:
            return
        if ask_confirm(self, f"Удалить зал «{self._halls[hall_id]['name']}» вместе со схемой мест?"):
            ok, _ = guarded(self, hall_service.delete_hall, self.user, hall_id)
            if ok:
                self._hall_id = None
                self.reload()
