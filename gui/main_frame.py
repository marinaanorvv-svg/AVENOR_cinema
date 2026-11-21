"""Главное окно: шапка, боковое меню по ролям и область экрана."""
import tkinter as tk
from tkinter import ttk

from services.permissions import Role

from . import neon
from . import palette as P
from . import theme
from .admin_tickets_frame import AdminTicketsFrame
from .buyer_film_frame import BuyerFilmFrame
from .buyer_home_frame import BuyerHomeFrame
from .buyer_orders_frame import BuyerOrdersFrame
from .buyer_poster_frame import BuyerPosterFrame
from .buyer_profile_frame import BuyerProfileFrame
from .buyer_tickets_frame import BuyerTicketsFrame
from .cashier_history_frame import CashierHistoryFrame
from .cashier_home_frame import CashierHomeFrame
from .cashier_refund_frame import CashierRefundFrame
from .cashier_sale_frame import CashierSaleFrame
from .cashier_search_frame import CashierSearchFrame
from .cashier_shift_frame import CashierShiftFrame
from .dashboard_frame import DashboardFrame
from .dialogs import ChangePasswordDialog
from .film_frame import FilmFrame
from .formatting import user_caption
from .halls_frame import HallsFrame
from .movies_frame import MoviesFrame
from .navigation import menu_for
from .reports_frame import ReportsFrame
from .schedule_frame import ScheduleFrame
from .sessions_frame import SessionsFrame
from .tickets_frame import MyTicketsFrame, TicketsFrame
from .users_frame import UsersFrame

# Ключ пункта меню (gui/navigation.py) -> класс экрана; конструктор: (parent, user).
SCREENS = {
    "schedule": ScheduleFrame, "tickets": TicketsFrame,
    "my_tickets": MyTicketsFrame, "movies": MoviesFrame, "halls": HallsFrame,
    "sessions": SessionsFrame, "reports": ReportsFrame, "users": UsersFrame,
}
# Экраны, которые есть только у администратора. «Билеты» у него расширенные (фильтры, подробности);
# у кассира тот же пункт меню открывает прежний экран из SCREENS.
ADMIN_SCREENS = {"dashboard": DashboardFrame, "tickets": AdminTicketsFrame}
# Разделы рабочего места кассира (пункты меню с правом USE_CASHIER_DESK, есть только у кассира).
CASHIER_SCREENS = {"cash_home": CashierHomeFrame, "sale": CashierSaleFrame, "search": CashierSearchFrame,
                   "refund": CashierRefundFrame, "history": CashierHistoryFrame, "shift": CashierShiftFrame}
# Разделы личного кабинета покупателя (пункты меню с правом USE_PORTAL, есть только у покупателя).
BUYER_SCREENS = {"buyer_home": BuyerHomeFrame, "poster": BuyerPosterFrame, "my_tickets": BuyerTicketsFrame,
                 "orders": BuyerOrdersFrame, "profile": BuyerProfileFrame}
SIDEBAR_WIDTH = 256
SLOGAN = "Больше, чем просто кино…"


class PlaceholderFrame(ttk.Frame):
    def __init__(self, parent, title):
        super().__init__(parent)
        ttk.Label(self, text=title, style="Header.TLabel").pack(anchor="w")
        ttk.Label(self, text="Раздел недоступен.").pack(anchor="w", pady=8)


class MainFrame(tk.Frame):
    def __init__(self, parent, user, on_logout):
        super().__init__(parent, bg=P.BG)
        self.user = user
        self.on_logout = on_logout
        self.menu = menu_for(user)
        self.allowed_keys = {item.key for item in self.menu}
        self.menu_buttons = {}
        self._build_ui()
        self.open_screen(self.menu[0].key)

    def _build_ui(self):
        header = tk.Frame(self, bg=P.BG)
        header.pack(side="top", fill="x")
        logo = tk.Canvas(header, width=270, height=68, bg=P.BG, bd=0, highlightthickness=0)
        logo.pack(side="left", fill="both", expand=True)   # шапка тянется на всю ширину: на ней тоже звёзды
        neon.draw_logo(logo, 24, 34)
        logo.bind("<Configure>", lambda event: neon.draw_stars(logo, event.width, event.height, 36))
        buttons = tk.Frame(header, bg=P.BG)
        buttons.pack(side="right", padx=22)
        neon.NeonButton(buttons, "Выйти", self.on_logout, style="ghost", height=36, icon="logout", bg=P.BG).pack(side="right", padx=(8, 0))
        neon.NeonButton(buttons, "Сменить пароль", self._change_password, style="ghost", height=36, bg=P.BG).pack(side="right")
        neon.NeonButton(buttons, user_caption(self.user), style="ghost", height=36,
                        icon="user", bg=P.BG, clickable=False).pack(side="right", padx=(0, 8))
        tk.Frame(self, bg=P.LINE, height=1).pack(fill="x")

        body = tk.Frame(self, bg=P.BG)
        body.pack(fill="both", expand=True)
        sky = tk.Canvas(body, bg=P.BG, bd=0, highlightthickness=0)   # звёздное небо за меню и панелью (создано первым — лежит ниже всех)
        sky.place(x=0, y=0, relwidth=1, relheight=1)
        sky.bind("<Configure>", lambda event: neon.draw_stars(sky, event.width, event.height, 120))
        sidebar = tk.Frame(body, bg=P.SIDEBAR, width=SIDEBAR_WIDTH)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(body, bg=P.LINE, width=1).pack(side="left", fill="y")

        menu_area = tk.Frame(sidebar, bg=P.SIDEBAR)
        menu_area.pack(fill="x", padx=6, pady=(18, 0))
        for item in self.menu:
            nav = neon.NavItem(menu_area, item.title, item.icon, command=lambda key=item.key: self.open_screen(key))
            nav.pack(pady=1)
            self.menu_buttons[item.key] = nav
        self.deco = tk.Canvas(sidebar, bg=P.SIDEBAR, bd=0, highlightthickness=0)
        self.deco.pack(fill="both", expand=True)
        self.deco.bind("<Configure>", self._draw_deco)

        panel = neon.RoundedPanel(body, fill=P.PANEL, bg=P.BG, pad=14)
        panel.pack(side="left", fill="both", expand=True, padx=16, pady=16)
        self.content = panel.body

    def _draw_deco(self, event):
        """Низ меню: звёзды, иллюстрация и слоган (иллюстрация — только если хватает высоты)."""
        self.deco.delete("all")
        neon.draw_stars(self.deco, event.width, event.height, 40)
        picture = theme.load_image("popcorn.png")
        slogan_y = event.height - 24
        if picture and event.height >= 380:
            self.deco.create_image(12, event.height - 12, image=picture, anchor="sw")
            slogan_y = event.height - 12 - picture.height() - 16
        self.deco.create_text(20, slogan_y, text=SLOGAN, anchor="sw", fill=P.MUTED, font=theme.font("nav"), width=SIDEBAR_WIDTH - 40)

    def open_screen(self, key, ticket_id=None, day=None):
        """Показывает экран, если он доступен роли (иначе вызов игнорируется).

        ticket_id — только для кассира: переход из поиска в «Возврат» сразу с номером билета."""
        if key not in self.allowed_keys:
            return
        for child in self.content.winfo_children():
            child.destroy()
        for button_key, button in self.menu_buttons.items():
            button.set_active(button_key == key)
        item = next(i for i in self.menu if i.key == key)
        factory = (ADMIN_SCREENS.get(key) if self.user.role == Role.ADMIN else None) or SCREENS.get(key)
        if self.user.role == Role.CASHIER:
            factory = CASHIER_SCREENS.get(key) or factory
        if self.user.role == Role.VIEWER:
            factory = BUYER_SCREENS.get(key) or factory
        screen = factory(self.content, self.user) if factory else PlaceholderFrame(self.content, item.title)
        if isinstance(screen, ScheduleFrame):
            screen.on_open = self._open_film
        if factory in CASHIER_SCREENS.values():
            screen.navigate = self.open_screen
        if self.user.role == Role.VIEWER and factory in BUYER_SCREENS.values():
            screen.navigate = self.open_screen
            screen.open_movie = self._open_buyer_film
            screen.logout = self.on_logout
        screen.pack(fill="both", expand=True)
        if day is not None and hasattr(screen, "set_day"):
            screen.set_day(day)
        if ticket_id is not None and hasattr(screen, "load_ticket"):
            screen.load_ticket(ticket_id)

    def _open_film(self, movie_id, date_iso):
        """Нажали на постер: вместо афиши показываем только этот фильм, его сеансы и кресла."""
        for child in self.content.winfo_children():
            child.destroy()
        film = FilmFrame(self.content, self.user, movie_id, date_iso, on_back=lambda: self.open_screen("schedule"))
        film.pack(fill="both", expand=True)

    def _open_buyer_film(self, movie_id, date_iso=None):
        """Покупатель нажал на карточку фильма: страница фильма с сеансами, схемой зала и оформлением заказа."""
        for child in self.content.winfo_children():
            child.destroy()
        film = BuyerFilmFrame(self.content, self.user, movie_id, date_iso, on_back=lambda: self.open_screen("poster"))
        film.pack(fill="both", expand=True)

    def _change_password(self):
        ChangePasswordDialog(self, self.user)
