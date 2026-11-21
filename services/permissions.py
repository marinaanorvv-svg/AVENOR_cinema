"""Роли, права и текущий пользователь.

Принцип: каждая функция сервиса, которую нельзя вызывать всем, принимает
`actor: CurrentUser` и первой строкой делает actor.require(Permission.XXX).
Так запрет работает даже при «прямом обращении» к логике в обход GUI,
как требует ТЗ (п. 3.1); скрытые кнопки в меню — лишь удобство.
"""
from dataclasses import dataclass

from .errors import PermissionDenied


class Role:
    ADMIN = "admin"
    CASHIER = "cashier"
    VIEWER = "viewer"
    ALL = (ADMIN, CASHIER, VIEWER)


class Permission:
    # общие
    VIEW_SCHEDULE = "view_schedule"          # афиша и расписание
    # кассир
    VIEW_HALL_SCHEME = "view_hall_scheme"    # схема зала со свободными/занятыми местами
    SELL_TICKET = "sell_ticket"
    REFUND_TICKET = "refund_ticket"
    SEARCH_TICKETS = "search_tickets"
    # пользователь
    VIEW_OWN_TICKETS = "view_own_tickets"
    BUY_OWN_TICKET = "buy_own_ticket"        # пользователь покупает билеты только на себя
    # администратор
    MANAGE_MOVIES = "manage_movies"
    MANAGE_GENRES = "manage_genres"
    MANAGE_HALLS = "manage_halls"
    MANAGE_SESSIONS = "manage_sessions"
    VIEW_REPORTS = "view_reports"
    MANAGE_USERS = "manage_users"
    VIEW_DASHBOARD = "view_dashboard"        # главная панель администратора
    VIEW_ALL_TICKETS = "view_all_tickets"    # расширенный просмотр всех билетов (фильтры, продавец)
    # рабочее место кассира: смена, продажа с оплатой, история собственных продаж (только у роли кассира)
    USE_CASHIER_DESK = "use_cashier_desk"
    # личный кабинет покупателя: заказы, оплата, возврат собственных билетов, профиль (только у роли viewer)
    USE_PORTAL = "use_portal"
    REFUND_OWN_TICKET = "refund_own_ticket"


_ADMIN_ONLY = frozenset({
    Permission.MANAGE_MOVIES, Permission.MANAGE_GENRES, Permission.MANAGE_HALLS,
    Permission.MANAGE_SESSIONS, Permission.VIEW_REPORTS, Permission.MANAGE_USERS,
    Permission.VIEW_DASHBOARD, Permission.VIEW_ALL_TICKETS,
})
_CASHIER = frozenset({
    Permission.VIEW_SCHEDULE, Permission.VIEW_HALL_SCHEME, Permission.SELL_TICKET,
    Permission.REFUND_TICKET, Permission.SEARCH_TICKETS,
})
_CASHIER_DESK = frozenset({Permission.USE_CASHIER_DESK})   # есть только у кассира: у администратора меню не меняется
_BUYER_PORTAL = frozenset({Permission.USE_PORTAL, Permission.REFUND_OWN_TICKET})   # только у покупателя: у админа и кассира не появляются
_VIEWER = frozenset({Permission.VIEW_SCHEDULE, Permission.VIEW_OWN_TICKETS, Permission.BUY_OWN_TICKET})

# Матрица доступа из п. 3.1 ТЗ. Админ: «полный доступ» = всё, что есть у остальных + своё.
ROLE_PERMISSIONS = {
    # админ управляет, ищет билеты и оформляет возвраты, но сам билеты НЕ продаёт (это работа кассира и покупателя)
    Role.ADMIN: _ADMIN_ONLY | (_CASHIER - {Permission.SELL_TICKET}) | (_VIEWER - {Permission.BUY_OWN_TICKET}),
    Role.CASHIER: _CASHIER | _CASHIER_DESK,
    Role.VIEWER: _VIEWER | _BUYER_PORTAL,
}


@dataclass(frozen=True)
class CurrentUser:
    """Вошедший пользователь (без хеша пароля). Неизменяемый объект."""
    id: int
    username: str
    full_name: str
    role: str
    client_id: int | None = None

    def has_permission(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())

    def require(self, permission: str) -> None:
        """Бросает PermissionDenied, если права нет."""
        if not self.has_permission(permission):
            raise PermissionDenied("Недостаточно прав для выполнения этого действия.")
