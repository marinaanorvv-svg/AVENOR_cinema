"""Схема зала: настоящие «кресла» на звёздном фоне. Цвет кресла зависит от состояния места."""
import tkinter as tk

from . import neon
from . import palette as P
from . import theme

# состояние -> цвета деталей места: основа (back), блик сверху (hi), боковые валики (arm),
# нижний «язычок» (cushion), контур (line) и цвет номера (text)
SEAT_STYLES = {
    "free": {"back": "#c42fc0", "hi": "#e664d6", "arm": "#dc5cd2", "cushion": "#8e1f94", "line": "#f6a6ee", "text": "#ffffff"},
    "vip": {"back": "#d9961f", "hi": "#ffd37a", "arm": "#ffe2a0", "cushion": "#9a6a10", "line": "#ffe3a0", "text": "#2a1a00"},
    "sold": {"back": "#25104d", "hi": "#2e1760", "arm": "#33206e", "cushion": "#1d0b40", "line": "#3a2275", "text": "#6b568f"},
    "selected": {"back": "#c8a6f0", "hi": "#f2e4ff", "arm": "#ffffff", "cushion": "#9a78d0", "line": "#ffffff", "text": "#2a0a45"},
}
LEGEND = (("free", "Свободно"), ("vip", "VIP"), ("sold", "Занято"), ("selected", "Выбрано"))
HOVER_MIX = 0.3                     # насколько кресло светлеет под курсором (смесь с белым)
MIN_CELL, MAX_CELL = 22, 54         # размер ячейки места, px (подстраивается под размер окна: схема всегда видна целиком)
PITCH = 0.86                        # шаг рядов относительно размера ячейки (ряды стоят чуть теснее мест)
LEFT, TOP, BOTTOM = 40, 84, 44      # поля: слева — номера рядов, сверху — экран, снизу — легенда
HOVER_ROLES = ("back", "hi", "cushion", "arm")
BACKDROP = P.SIDEBAR


def seat_state(seat: dict, selected=()) -> str:
    """'sold' | 'selected' | 'vip' | 'free' — по данным места и набору выбранных id."""
    if seat.get("is_sold"):
        return "sold"
    if seat["id"] in selected:
        return "selected"
    return "vip" if seat["seat_type"] == "vip" else "free"


def cell_size(width: int, columns: int, height: int | None = None, rows: int = 1) -> int:
    """Размер ячейки так, чтобы весь зал влез в окно: и все места ряда по ширине, и все ряды по высоте."""
    size = max(width - LEFT - 16, MIN_CELL) / max(columns, 1)
    if height is not None:
        size = min(size, max(height - TOP - BOTTOM, MIN_CELL) / (max(rows, 1) * PITCH))
    return int(max(MIN_CELL, min(MAX_CELL, size)))


def chair_shapes(x, y, size):
    """Детали места в ячейке (x, y — левый верхний угол): [(роль, точки многоугольника)].

    Мягкое кресло, как на макете: скруглённая основа, светлый блик сверху, боковые валики и небольшой
    «язычок» снизу. Размеры считаются от размера ячейки, поэтому места выглядят одинаково в любом зале.
    """
    u = size / 46
    return [
        ("arm", P.rounded_points(x + 1.5 * u, y + 10 * u, x + 8 * u, y + 34 * u, 3.5 * u)),
        ("arm", P.rounded_points(x + 38 * u, y + 10 * u, x + 44.5 * u, y + 34 * u, 3.5 * u)),
        ("back", P.rounded_points(x + 5 * u, y + 4 * u, x + 41 * u, y + 34 * u, 10 * u)),
        ("hi", P.rounded_points(x + 8.5 * u, y + 6.5 * u, x + 37.5 * u, y + 19 * u, 7 * u)),
        ("cushion", P.rounded_points(x + 16 * u, y + 33 * u, x + 30 * u, y + 38.5 * u, 2.5 * u)),
    ]


class SeatMap(tk.Canvas):
    """Рисует места как кресла. on_click(seat_dict) вызывается при нажатии на свободное или выбранное место."""

    def __init__(self, parent, on_click=None):
        super().__init__(parent, bg=BACKDROP, bd=0, highlightthickness=0, width=300, height=150)   # маленький «желаемый» размер: дальше холст растягивается по окну, а не выдавливает кнопки
        self.on_click = on_click
        self.seat_items = {}      # id места -> [(элемент холста, роль детали)], для подсветки под курсором
        self._rows, self._selected, self._drawn_size = [], (), (0, 0)
        self.bind("<Configure>", self._on_resize)

    # ------------------------------------------------------------------ рисование
    def render(self, rows, selected=()) -> None:
        """rows — как в ticket_service.get_session_seat_map / hall_service.get_hall_scheme."""
        self._rows, self._selected = rows, selected
        self._draw()

    def _on_resize(self, event=None):
        size = (self.winfo_width(), self.winfo_height())
        if abs(size[0] - self._drawn_size[0]) > 8 or abs(size[1] - self._drawn_size[1]) > 8:
            self._draw()      # окно изменилось — подгоняем размер кресел и звёздное небо

    def _draw(self):
        rows = self._rows
        self.delete("all")
        self.seat_items = {}
        columns = max((len(row["seats"]) for row in rows), default=0)
        width, height = max(self.winfo_width(), 420), max(self.winfo_height(), 260)
        self._drawn_size = (self.winfo_width(), self.winfo_height())
        size = cell_size(width, columns or 8, height, len(rows) or 3)
        neon.draw_stars(self, width, height, 90)
        if not rows:
            self.create_text(width // 2, height // 2, text="Выберите время сеанса", fill=P.MUTED,
                             font=theme.font("body"))
            self._screen(width // 2, max(columns, 8) * size)
            return
        hall_w = columns * size
        start_x = max(LEFT, (width - hall_w) // 2 + LEFT // 3)
        self._screen(start_x + hall_w // 2, hall_w)
        for c_index in range(columns):             # номера мест над первым рядом
            self.create_text(start_x + c_index * size + size * 0.5, TOP - 12, text=str(c_index + 1), fill=P.MUTED,
                             font=theme.font("small"))
        for r_index, row in enumerate(rows):
            y = TOP + r_index * size * PITCH
            self.create_text(start_x - 14, y + size * 0.42, text=str(row["row_number"]), fill=P.MUTED,
                             font=theme.font("small"))
            for c_index, seat in enumerate(row["seats"]):
                self._chair(start_x + c_index * size, y, size, seat)
        self._legend(width // 2, height - 22)

    def _screen(self, cx, hall_w):
        """Светящийся экран над залом."""
        half = max(hall_w, 200) // 2
        for grow, mix in ((10, 0.82), (6, 0.62), (3, 0.4)):   # «свечение»: слои светлее к центру
            self.create_polygon(P.rounded_points(cx - half - grow, 18 - grow, cx + half + grow, 30 + grow, 8),
                                smooth=True, fill=P.blend("#e9b8ff", BACKDROP, mix), outline="")
        self.create_polygon(P.rounded_points(cx - half, 18, cx + half, 30, 6), smooth=True, fill="#f4d4ff", outline="")
        self.create_text(cx, 52, text="Э К Р А Н", fill=P.MUTED, font=theme.font("small"))

    def _chair(self, x, y, size, seat):
        state = seat_state(seat, self._selected)
        look = SEAT_STYLES[state]
        tag = f"seat{seat['id']}"
        items = []
        if state == "selected":   # ореол вокруг выбранного кресла
            items.append((self.create_polygon(
                P.rounded_points(x, y + size * 0.02, x + size, y + size * 0.88, 12), smooth=True, fill="",
                outline=P.ACCENT_SOFT, width=2, tags=tag), "halo"))
        for role, points in chair_shapes(x, y, size):
            items.append((self.create_polygon(points, smooth=True, fill=look[role], outline=look["line"],
                                              width=1, tags=tag), role))
        if state == "selected":                    # номер виден только у выбранного места (остальные — по цифрам сверху)
            items.append((self.create_text(x + size * 0.5, y + size * 0.4, text=str(seat["seat_number"]),
                                           fill=look["text"], font=theme.font("bold"), tags=tag), "text"))
        self.seat_items[seat["id"]] = items
        if state == "sold":
            return          # занятое место: без подсветки и без нажатия
        self.tag_bind(tag, "<Button-1>", lambda event, s=seat: self._clicked(s))
        self.tag_bind(tag, "<Enter>", lambda event, s=seat, st=state: self._hover(s["id"], st, True))
        self.tag_bind(tag, "<Leave>", lambda event, s=seat, st=state: self._hover(s["id"], st, False))

    def _hover(self, seat_id, state, inside):
        """Под курсором кресло светлеет, курсор становится «рукой»."""
        look = SEAT_STYLES[state]
        for item, role in self.seat_items.get(seat_id, ()):
            if role in HOVER_ROLES:
                self.itemconfigure(item, fill=P.blend(look[role], "#ffffff", HOVER_MIX) if inside else look[role])
        self.configure(cursor="hand2" if inside else "arrow")

    def _legend(self, cx, cy):
        """Подписи состояний: маленькое кресло и слово."""
        face = theme.font("small")
        gap = 22
        widths = [theme.text_width(face, title) + 34 for _, title in LEGEND]
        x = cx - (sum(widths) + gap * (len(LEGEND) - 1)) // 2
        for (state, title), w in zip(LEGEND, widths):
            look = SEAT_STYLES[state]
            self.create_polygon(P.rounded_points(x, cy - 7, x + 22, cy + 7, 5), smooth=True, fill=look["back"],
                                outline=look["line"])
            self.create_text(x + 30, cy, text=title, anchor="w", fill=P.TEXT, font=face)
            x += w + gap

    def _clicked(self, seat) -> None:
        if self.on_click:
            self.on_click(seat)
