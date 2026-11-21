"""Меню по ролям (без tkinter).

Пункт показывается, только если у пользователя есть нужное право. Это удобство;
настоящая защита — actor.require(...) внутри сервисов.
"""
from dataclasses import dataclass

from services.permissions import CurrentUser, Permission


@dataclass(frozen=True)
class MenuItem:
    key: str
    title: str
    permission: str
    needs_client: bool = False   # пункт имеет смысл только для учётки, привязанной к клиенту
    icon: str = "home"          # имя иконки из gui/assets (см. assets_spec.ICON_NAMES)
    hidden_for: tuple = ()      # роли, у которых пункт скрыт, хотя право есть (у кассира их заменяют свои разделы)


MENU_ITEMS = (
    MenuItem("dashboard", "Главная", Permission.VIEW_DASHBOARD, icon="dashboard"),   # только администратор
    # рабочее место кассира (право USE_CASHIER_DESK есть только у кассира)
    MenuItem("cash_home", "Главная", Permission.USE_CASHIER_DESK, icon="dashboard"),
    MenuItem("sale", "Продажа билетов", Permission.USE_CASHIER_DESK, icon="ticket"),
    MenuItem("search", "Поиск билетов", Permission.USE_CASHIER_DESK, icon="search"),
    MenuItem("refund", "Возврат билетов", Permission.USE_CASHIER_DESK, icon="refund"),
    MenuItem("history", "История продаж", Permission.USE_CASHIER_DESK, icon="history"),
    MenuItem("shift", "Смена", Permission.USE_CASHIER_DESK, icon="shift"),
    # личный кабинет покупателя (право USE_PORTAL есть только у покупателя); «Мои билеты» — ниже, прежний ключ my_tickets
    MenuItem("buyer_home", "Главная", Permission.USE_PORTAL, icon="home"),
    MenuItem("poster", "Афиша", Permission.USE_PORTAL, icon="film"),
    MenuItem("schedule", "Афиша", Permission.VIEW_SCHEDULE, icon="home", hidden_for=("cashier", "viewer", "admin")),   # у покупателя своя афиша; админ билеты не продаёт
    MenuItem("tickets", "Билеты и возвраты", Permission.SEARCH_TICKETS, icon="history", hidden_for=("cashier",)),
    MenuItem("my_tickets", "Мои билеты", Permission.VIEW_OWN_TICKETS, needs_client=True, icon="ticket"),
    MenuItem("orders", "История покупок", Permission.USE_PORTAL, needs_client=True, icon="history"),
    MenuItem("profile", "Личный кабинет", Permission.USE_PORTAL, icon="user"),
    MenuItem("movies", "Фильмы", Permission.MANAGE_MOVIES, icon="film"),
    MenuItem("halls", "Залы", Permission.MANAGE_HALLS, icon="seat"),
    MenuItem("sessions", "Сеансы", Permission.MANAGE_SESSIONS, icon="calendar"),
    MenuItem("reports", "Отчёты", Permission.VIEW_REPORTS, icon="chart"),
    MenuItem("users", "Пользователи", Permission.MANAGE_USERS, icon="users"),
)


def menu_for(user: CurrentUser) -> list[MenuItem]:
    return [item for item in MENU_ITEMS
            if user.has_permission(item.permission) and user.role not in item.hidden_for
            and (not item.needs_client or user.client_id is not None)]
