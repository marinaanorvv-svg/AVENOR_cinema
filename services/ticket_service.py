"""Продажа и возврат билетов, схема мест сеанса, поиск, «мои билеты»."""
import sqlite3
from datetime import datetime

from database import crud
from database.connection import connection, transaction
from database.errors import ConstraintError, DBError

from . import clock
from .client_service import resolve_client, validate_client_input
from .errors import PermissionDenied, ValidationError
from .permissions import CurrentUser, Permission
from .session_service import decorate_session
from .validators import db_error_to_validation, parse_date, parse_int

SOLD = "sold"
RETURNED = "returned"
_DB_BUSY_MSG = "База данных занята другой операцией. Повторите попытку."


# ------------------------------------------------------------------ вспомогательное

def _now() -> datetime:
    return clock.now()


def _session_start(session_row) -> datetime:
    return datetime.strptime(f"{session_row['session_date']} {session_row['session_time']}",
                             "%Y-%m-%d %H:%M")


def _seat_label(row_number, seat_number) -> str:
    return f"ряд {row_number}, место {seat_number}"


REASON_ALREADY_RETURNED = "Билет уже возвращён: повторный возврат невозможен."
REASON_SESSION_STARTED = "Сеанс уже начался: возврат невозможен."


def refund_block_reason(status: str, session_started: bool) -> str:
    """ЕДИНОЕ правило возврата: пустая строка — возврат разрешён, иначе причина отказа.

    Его используют транзакция возврата, проверки кассира и покупателя и все экраны, поэтому интерфейс
    не может разрешить то, что запрещает сервис, и наоборот.
    """
    if status != SOLD:
        return REASON_ALREADY_RETURNED
    if session_started:
        return REASON_SESSION_STARTED
    return ""


def _decorate_ticket(row) -> dict:
    """Добавляет поля для GUI: подпись места, начался ли сеанс, можно ли вернуть билет и почему нельзя."""
    item = dict(row)
    item["seat_label"] = _seat_label(item["row_number"], item["seat_number"])
    item["session_started"] = _now() >= _session_start(item)
    item["refund_reason"] = refund_block_reason(item["status"], item["session_started"])
    item["is_refundable"] = not item["refund_reason"]
    return item


def _blank_to_none(value):
    return None if value is None or (isinstance(value, str) and not value.strip()) else value


# ------------------------------------------------------------------ схема мест сеанса

def get_session_seat_map(actor: CurrentUser, session_id: int, db_path=None) -> dict:
    """Схема зала для выбранного сеанса с отметкой свободных/занятых мест.

    {"session": {...},                       # данные сеанса (см. session_service)
     "is_open_for_sale": bool,               # False, если сеанс уже начался
     "rows": [{"row_number": 1, "seats": [
         {"id", "seat_number", "seat_type", "is_sold", "ticket_id"}]}]}
    """
    if not actor.has_permission(Permission.BUY_OWN_TICKET):   # пользователь видит схему, чтобы выбрать места
        actor.require(Permission.VIEW_HALL_SCHEME)
    session_id = parse_int(session_id, "Сеанс", 1)
    with connection(db_path) as conn:
        session = crud.get_session_detailed(conn, session_id)
        if session is None:
            raise ValidationError("Сеанс не найден.")
        seats = crud.list_seats_by_hall(conn, session["hall_id"])
        sold = {t["seat_id"]: t["id"] for t in crud.list_sold_tickets_by_session(conn, session_id)}
    rows: dict[int, list] = {}
    for seat in seats:
        rows.setdefault(seat["row_number"], []).append({
            "id": seat["id"], "seat_number": seat["seat_number"], "seat_type": seat["seat_type"],
            "is_sold": seat["id"] in sold, "ticket_id": sold.get(seat["id"])})
    return {"session": decorate_session(session),
            "is_open_for_sale": _now() < _session_start(session),
            "rows": [{"row_number": r, "seats": rows[r]} for r in sorted(rows)]}


# ------------------------------------------------------------------ продажа

MAX_SEATS_PER_PURCHASE = 10


PAYMENT_METHODS = ("cash", "card")


def _validate_sale_info(info) -> dict:
    method = info.get("payment_method") if isinstance(info, dict) else None
    if method not in PAYMENT_METHODS:
        raise ValidationError("Выберите способ оплаты: наличные или карта.")
    return {"payment_method": method, "shift_id": parse_int(info.get("shift_id"), "Смена", 1)}


PAYMENT_METHODS_ONLINE = ("card",)


def _validate_order_info(info) -> dict:
    method = info.get("payment_method") if isinstance(info, dict) else None
    if method not in PAYMENT_METHODS_ONLINE:
        raise ValidationError("Выберите способ оплаты.")
    return {"payment_method": method}


def sell_tickets(actor: CurrentUser, session_id, seat_ids, client, db_path=None, sale_info=None,
                 order_info=None) -> list[dict]:
    """Продаёт билеты на несколько мест одного сеанса ОДНОЙ клиентской покупкой.

    Всё или ничего: если хотя бы одно место занято или не подходит, не оформляется
    ни один билет и не создаётся клиент. Возвращает список билетов (для чека).
    client — id существующего клиента или {"full_name", "phone", "email"}.

    sale_info — только для рабочего места кассира: {"payment_method": "cash"|"card", "shift_id": id открытой смены}.
    С ним в той же транзакции создаётся запись о продаже (чек) и билеты привязываются к ней; без него
    поведение прежнее (афиша администратора, покупки пользователя).

    order_info — только для личного кабинета покупателя: {"payment_method": "card"}. В той же транзакции создаётся
    заказ покупателя и билеты привязываются к нему; отменённый сеанс купить нельзя.

    Защита от двойной продажи в три слоя:
      1. BEGIN IMMEDIATE (см. connection.transaction): запись одновременно идёт только
         из одной транзакции, поэтому проверка «место свободно» и вставка билета
         не могут быть разорваны другой продажей;
      2. явная проверка занятости с понятным сообщением;
      3. частичный UNIQUE-индекс в БД — последняя страховка, даже если код ошибся.
    """
    if not actor.has_permission(Permission.SELL_TICKET):
        # Покупатель покупает только для себя: клиент — его собственная карточка, чужие данные игнорируются.
        actor.require(Permission.BUY_OWN_TICKET)
        if actor.client_id is None:
            raise ValidationError("Учётная запись не привязана к клиенту: покупка недоступна.")
        client = actor.client_id
    if sale_info is not None:
        actor.require(Permission.USE_CASHIER_DESK)
        sale_info = _validate_sale_info(sale_info)
    if order_info is not None:
        actor.require(Permission.USE_PORTAL)
        order_info = _validate_order_info(order_info)
    session_id = parse_int(session_id, "Сеанс", 1)
    if isinstance(seat_ids, (str, bytes)) or not hasattr(seat_ids, "__iter__"):
        raise ValidationError("Выберите места.")
    unique_ids = []
    for value in seat_ids:
        seat_id = parse_int(value, "Место", 1)
        if seat_id not in unique_ids:   # одно и то же место дважды — считаем один раз
            unique_ids.append(seat_id)
    if not unique_ids:
        raise ValidationError("Выберите хотя бы одно место.")
    if len(unique_ids) > MAX_SEATS_PER_PURCHASE:
        raise ValidationError(
            f"За одну покупку можно оформить не более {MAX_SEATS_PER_PURCHASE} билетов.")
    client = validate_client_input(client)   # проверяем ввод до блокировки БД
    try:
        with transaction(db_path) as conn:
            session = crud.get_session_detailed(conn, session_id)
            if session is None:
                raise ValidationError("Сеанс не найден.")
            if _now() >= _session_start(session):
                raise ValidationError("Сеанс уже начался: продажа билетов закрыта.")
            if order_info is not None and session["is_cancelled"]:
                raise ValidationError("Сеанс отменён: покупка билетов недоступна.")
            seats = []
            for seat_id in unique_ids:   # сначала проверяем ВСЕ места, потом что-либо пишем
                seat = crud.get_seat(conn, seat_id)
                if seat is None:
                    raise ValidationError("Место не найдено.")
                if seat["hall_id"] != session["hall_id"]:
                    raise ValidationError("Это место не относится к залу выбранного сеанса.")
                if crud.get_sold_ticket(conn, session_id, seat_id) is not None:
                    raise ValidationError(
                        f"Место уже занято ({_seat_label(seat['row_number'], seat['seat_number'])}). "
                        "Выберите другое.")
                seats.append(seat)
            client_id = resolve_client(conn, client)
            purchase_date = _now().strftime("%Y-%m-%d %H:%M:%S")
            ticket_ids = [crud.create_ticket(conn, session_id, seat["id"], client_id,
                                             purchase_date=purchase_date, seller_id=actor.id) for seat in seats]
            if sale_info is not None:
                shift = crud.get_shift(conn, sale_info["shift_id"])
                if shift is None or shift["cashier_id"] != actor.id or shift["closed_at"] is not None:
                    raise ValidationError("Смена закрыта. Откройте смену, чтобы продавать билеты.")
                sale_id = crud.create_sale(conn, actor.id, shift["id"], session_id, client_id,
                                           sale_info["payment_method"], round(session["price"] * len(seats), 2),
                                           purchase_date)
                for ticket_id in ticket_ids:
                    crud.update_ticket(conn, ticket_id, sale_id=sale_id)
            if order_info is not None:
                order_id = crud.create_order(conn, actor.id, client_id, session_id, order_info["payment_method"],
                                             round(session["price"] * len(seats), 2), purchase_date)
                for ticket_id in ticket_ids:
                    crud.update_ticket(conn, ticket_id, order_id=order_id)
            created = [crud.get_ticket_detailed(conn, ticket_id) for ticket_id in ticket_ids]
        return [_decorate_ticket(row) for row in created]
    except ConstraintError as exc:
        if exc.kind == "unique":   # сработала страховка уровня БД
            raise ValidationError("Место уже занято. Выберите другое.") from exc
        raise db_error_to_validation(exc) from exc
    except DBError as exc:
        raise db_error_to_validation(exc) from exc
    except sqlite3.OperationalError as exc:   # например, «database is locked»
        raise ValidationError(_DB_BUSY_MSG) from exc


def sell_ticket(actor: CurrentUser, session_id, seat_id, client, db_path=None) -> dict:
    """Продажа одного билета (то же, что sell_tickets с одним местом)."""
    return sell_tickets(actor, session_id, [seat_id], client, db_path)[0]


# ------------------------------------------------------------------ возврат

def _refund(actor: CurrentUser, ticket_id, db_path=None, own_only=False) -> dict:
    """Общее ядро возврата для кассы/администратора и для покупателя (own_only: билет должен быть его собственным)."""
    ticket_id = parse_int(ticket_id, "Номер билета", 1)
    try:
        with transaction(db_path) as conn:
            ticket = crud.get_ticket_detailed(conn, ticket_id)
            if ticket is None:
                raise ValidationError("Билет не найден.")
            if own_only and (actor.client_id is None or ticket["client_id"] != actor.client_id):
                raise PermissionDenied("Недостаточно прав для возврата этого билета.")
            reason = refund_block_reason(ticket["status"], _now() >= _session_start(ticket))
            if reason:
                raise ValidationError(reason)
            crud.update_ticket(conn, ticket_id, status=RETURNED,
                               returned_at=_now().strftime("%Y-%m-%d %H:%M:%S"), refunded_by=actor.id)
            ticket = crud.get_ticket_detailed(conn, ticket_id)
        return _decorate_ticket(ticket)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc
    except sqlite3.OperationalError as exc:
        raise ValidationError(_DB_BUSY_MSG) from exc


def refund_ticket(actor: CurrentUser, ticket_id, db_path=None) -> dict:
    """Возврат билета: статус sold -> returned, место снова становится свободным.

    Нельзя вернуть уже возвращённый билет и билет на начавшийся сеанс.
    """
    actor.require(Permission.REFUND_TICKET)
    return _refund(actor, ticket_id, db_path)


def refund_own_ticket(actor: CurrentUser, ticket_id, db_path=None) -> dict:
    """Покупатель возвращает СВОЙ билет по тем же правилам, что и касса (проверка владельца — внутри транзакции)."""
    actor.require(Permission.REFUND_OWN_TICKET)
    return _refund(actor, ticket_id, db_path, own_only=True)


# ------------------------------------------------------------------ поиск и просмотр

def search_tickets(actor: CurrentUser, ticket_id=None, client=None, session_id=None,
                   date=None, status=None, db_path=None) -> list[dict]:
    """Поиск билетов (кассир/админ). Все условия необязательны и объединяются по «И».

    client — часть ФИО, email или телефона. Текстовый поиск делаем в Python:
    SQLite не умеет регистронезависимый поиск по кириллице.
    """
    actor.require(Permission.SEARCH_TICKETS)
    ticket_id, session_id = _blank_to_none(ticket_id), _blank_to_none(session_id)
    date, status = _blank_to_none(date), _blank_to_none(status)
    if ticket_id is not None:
        ticket_id = parse_int(ticket_id, "Номер билета", 1)
    if session_id is not None:
        session_id = parse_int(session_id, "Сеанс", 1)
    if date is not None:
        date = parse_date(date, "Дата сеанса").isoformat()
    if status is not None and status not in (SOLD, RETURNED):
        raise ValidationError("Статус: sold (продан) или returned (возвращён).")

    with connection(db_path) as conn:
        rows = crud.list_tickets_detailed(conn, ticket_id=ticket_id, session_id=session_id,
                                          status=status, date_from=date, date_to=date)
    tickets = [_decorate_ticket(r) for r in rows]

    needle = (client or "").strip().casefold() if isinstance(client, str) else ""
    if needle:
        digits = "".join(ch for ch in needle if ch.isdigit())

        def matches(t):
            phone_digits = "".join(ch for ch in (t["client_phone"] or "") if ch.isdigit())
            return (needle in t["client_name"].casefold()
                    or needle in (t["client_email"] or "").casefold()
                    or (len(digits) >= 3 and digits in phone_digits))
        tickets = [t for t in tickets if matches(t)]
    return tickets


def get_ticket(actor: CurrentUser, ticket_id, db_path=None) -> dict:
    """Один билет. Кассир/админ видят любой, пользователь — только свой."""
    ticket_id = parse_int(ticket_id, "Номер билета", 1)
    with connection(db_path) as conn:
        row = crud.get_ticket_detailed(conn, ticket_id)
    if row is None:
        raise ValidationError("Билет не найден.")
    if not actor.has_permission(Permission.SEARCH_TICKETS):
        # проверка на уровне объекта: чужие билеты пользователь увидеть не должен
        actor.require(Permission.VIEW_OWN_TICKETS)
        if actor.client_id is None or row["client_id"] != actor.client_id:
            raise PermissionDenied("Недостаточно прав для просмотра этого билета.")
    return _decorate_ticket(row)


def list_my_tickets(actor: CurrentUser, db_path=None) -> list[dict]:
    """История билетов вошедшего пользователя (новые сеансы — первыми)."""
    actor.require(Permission.VIEW_OWN_TICKETS)
    if actor.client_id is None:   # например, у администратора нет клиентской карточки
        return []
    with connection(db_path) as conn:
        rows = crud.list_tickets_detailed(conn, client_id=actor.client_id)
    tickets = [_decorate_ticket(r) for r in rows]
    return sorted(tickets, key=lambda t: (t["session_date"], t["session_time"]), reverse=True)
