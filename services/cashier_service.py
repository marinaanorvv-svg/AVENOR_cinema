"""Рабочее место кассира: смены, продажа с оплатой, поиск и возврат билетов, история собственных продаж.

Принципы:
  - права проверяются здесь (actor.require), а не только скрытием кнопок: всё это доступно только кассиру;
  - продажа и возврат выполняет прежний ticket_service (транзакции, защита от двойной продажи) — логика не дублируется;
  - кассир видит только собственные продажи и смены, финансовой статистики всего кинотеатра у него нет.
"""
from datetime import datetime, timedelta

from database import cashier_queries, crud
from database.connection import connection, transaction
from database.errors import DBError

from . import clock, session_service, ticket_service
from .errors import ValidationError
from .permissions import CurrentUser, Permission
from .ticket_print import PAYMENT_TITLES
from .validators import db_error_to_validation, parse_date, parse_int

SALE_DAYS = 14                 # на сколько дней вперёд кассир видит сеансы для продажи
UPCOMING_LIMIT = 8
RECENT_LIMIT = 8
PAYMENT_OPTIONS = (("cash", "Наличные"), ("card", "Банковская карта"))
SALE_STATUSES = (("sold", "Оформлена"), ("partial", "Частично возвращена"), ("returned", "Возвращена"))
_SHIFT_CLOSED_MSG = "Смена не открыта. Откройте смену в разделе «Смена»."


def _now() -> datetime:
    return clock.now()


def _stamp(moment=None) -> str:
    return (moment or _now()).strftime("%Y-%m-%d %H:%M:%S")


def _desk(actor: CurrentUser) -> None:
    actor.require(Permission.USE_CASHIER_DESK)


def _money(value) -> float:
    return round(float(value or 0), 2)


# ------------------------------------------------------------------ смена

def _shift_dict(row) -> dict:
    return dict(row) if row is not None else None


def current_shift(actor: CurrentUser, db_path=None) -> dict | None:
    """Открытая смена кассира или None."""
    _desk(actor)
    with connection(db_path) as conn:
        return _shift_dict(cashier_queries.get_open_shift(conn, actor.id))


def _require_open_shift(actor: CurrentUser, db_path=None) -> dict:
    shift = current_shift(actor, db_path)
    if shift is None:
        raise ValidationError(_SHIFT_CLOSED_MSG)
    return shift


def _summary(conn, shift) -> dict:
    """Итоги смены: продажи, билеты, возвраты и суммы (в том числе по способам оплаты)."""
    end = shift["closed_at"] or _stamp()
    sold = {r["method"]: r for r in cashier_queries.sales_totals(conn, shift["id"])}
    back = {r["method"]: r for r in cashier_queries.refund_totals(conn, shift["cashier_id"], shift["opened_at"], end)}
    methods = []
    for method in [m for m, _ in PAYMENT_OPTIONS] + sorted((set(sold) | set(back)) - {"cash", "card"}):
        s, r = sold.get(method), back.get(method)
        if not s and not r and method not in ("cash", "card"):
            continue
        sales_amount, refund_amount = _money(s["amount"] if s else 0), _money(r["amount"] if r else 0)
        methods.append({"method": method, "title": PAYMENT_TITLES.get(method, method),
                        "sales_amount": sales_amount, "refund_amount": refund_amount,
                        "net": _money(sales_amount - refund_amount)})
    sales_amount = _money(sum(m["sales_amount"] for m in methods))
    refund_amount = _money(sum(m["refund_amount"] for m in methods))
    return {
        "shift": dict(shift), "is_open": shift["closed_at"] is None,
        "sales_count": sum(r["sales"] for r in sold.values()),
        "tickets_sold": sum(r["tickets"] for r in sold.values()),
        "sales_amount": sales_amount,
        "returns_count": sum(r["tickets"] for r in back.values()),
        "refund_amount": refund_amount,
        "net_amount": _money(sales_amount - refund_amount),
        "by_method": methods,
    }


def empty_summary() -> dict:
    return {"shift": None, "is_open": False, "sales_count": 0, "tickets_sold": 0, "sales_amount": 0.0,
            "returns_count": 0, "refund_amount": 0.0, "net_amount": 0.0, "by_method": []}


def open_shift(actor: CurrentUser, db_path=None) -> dict:
    """Начало смены: фиксируется время открытия; одновременно у кассира только одна открытая смена."""
    _desk(actor)
    try:
        with transaction(db_path) as conn:
            if cashier_queries.get_open_shift(conn, actor.id) is not None:
                raise ValidationError("Смена уже открыта.")
            shift_id = crud.create_shift(conn, actor.id, _stamp())
            return dict(crud.get_shift(conn, shift_id))
    except DBError as exc:                # сработал уникальный индекс: смену успели открыть с другого места
        raise ValidationError("Смена уже открыта.") from exc


def close_shift(actor: CurrentUser, db_path=None) -> dict:
    """Завершение смены. Возвращает итоговый отчёт (см. shift_summary)."""
    _desk(actor)
    with transaction(db_path) as conn:
        shift = cashier_queries.get_open_shift(conn, actor.id)
        if shift is None:
            raise ValidationError("Нет открытой смены.")
        crud.update_shift(conn, shift["id"], closed_at=_stamp())
        return _summary(conn, crud.get_shift(conn, shift["id"]))


def shift_summary(actor: CurrentUser, shift_id=None, db_path=None) -> dict:
    """Итоги смены (по умолчанию — текущей). Чужие смены недоступны. Нет смены -> нулевые итоги."""
    _desk(actor)
    with connection(db_path) as conn:
        if shift_id is None:
            shift = cashier_queries.get_open_shift(conn, actor.id)
            return _summary(conn, shift) if shift is not None else empty_summary()
        shift = crud.get_shift(conn, parse_int(shift_id, "Смена", 1))
        if shift is None or shift["cashier_id"] != actor.id:
            raise ValidationError("Смена не найдена.")
        return _summary(conn, shift)


def list_my_shifts(actor: CurrentUser, db_path=None) -> list[dict]:
    """Последние смены кассира с итогами."""
    _desk(actor)
    with connection(db_path) as conn:
        return [_summary(conn, s) for s in cashier_queries.list_shifts(conn, actor.id)]


def shift_report_text(summary: dict, cashier_name: str = "") -> str:
    """Итоговый отчёт смены в виде текста (для окна и сохранения в файл)."""
    shift = summary["shift"]
    if shift is None:
        return "Смена не открыта."

    def money(value):
        return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"

    def when(text):
        return f"{text[8:10]}.{text[5:7]}.{text[0:4]} {text[11:16]}" if text else "—"

    lines = ["AVENOR — отчёт по смене", f"Смена № {shift['id']}" + (f", кассир: {cashier_name}" if cashier_name else ""),
             f"Открыта: {when(shift['opened_at'])}",
             f"Закрыта: {when(shift['closed_at']) if shift['closed_at'] else 'ещё идёт'}", "",
             f"Продаж: {summary['sales_count']}", f"Продано билетов: {summary['tickets_sold']}",
             f"Сумма продаж: {money(summary['sales_amount'])}",
             f"Возвратов (билетов): {summary['returns_count']}", f"Сумма возвратов: {money(summary['refund_amount'])}",
             f"ИТОГО за смену: {money(summary['net_amount'])}", "", "По способам оплаты (продажи − возвраты):"]
    for m in summary["by_method"]:
        lines.append(f"  {m['title']}: {money(m['sales_amount'])} − {money(m['refund_amount'])} = {money(m['net'])}")
    return "\n".join(lines)


# ------------------------------------------------------------------ выбор фильма и сеанса

def _sellable_sessions(actor, db_path):
    today = _now().date()
    sessions = session_service.list_sessions(actor, date_from=today.isoformat(),
                                             date_to=(today + timedelta(days=SALE_DAYS)).isoformat(), db_path=db_path)
    return [s for s in sessions if not s["started"]]


def list_sellable_movies(actor: CurrentUser, db_path=None) -> list[dict]:
    """Фильмы, на которые сейчас можно продать билет: есть неначавшийся сеанс. Отменённые сеансы не учитываются."""
    _desk(actor)
    movies: dict[int, dict] = {}
    for s in _sellable_sessions(actor, db_path):
        m = movies.setdefault(s["movie_id"], {
            "id": s["movie_id"], "title": s["movie_title"], "genre_name": s["genre_name"], "duration": s["duration"],
            "age_rating": s["age_rating"], "description": s["description"], "poster_path": s["poster_path"],
            "sessions": 0, "free_seats": 0})
        m["sessions"] += 1
        m["free_seats"] += s["seats_free"]
    return sorted(movies.values(), key=lambda m: m["title"].casefold())


def list_movie_days(actor: CurrentUser, movie_id, db_path=None) -> dict[str, list[dict]]:
    """Сеансы фильма по датам (только ещё не начавшиеся), даты по возрастанию."""
    _desk(actor)
    movie_id = parse_int(movie_id, "Фильм", 1)
    days: dict[str, list[dict]] = {}
    for s in _sellable_sessions(actor, db_path):
        if s["movie_id"] == movie_id:
            days.setdefault(s["session_date"], []).append(s)
    return days


# ------------------------------------------------------------------ стоимость и доступность мест

def quote(actor: CurrentUser, session_id, seat_ids, db_path=None) -> dict:
    """Актуальная проверка выбранных мест и расчёт стоимости.

    Возвращает {"session", "lines": [{seat_id, label, category, price}], "count", "total", "unavailable": [seat_id],
    "open": можно ли продавать}. Места, которые уже заняты (например, продало другое рабочее место),
    попадают в "unavailable" и в стоимость не входят.
    """
    _desk(actor)
    actor.require(Permission.SELL_TICKET)
    data = ticket_service.get_session_seat_map(actor, session_id, db_path)
    price = float(data["session"]["price"])
    wanted = list(dict.fromkeys(seat_ids))
    seats = {s["id"]: (row["row_number"], s) for row in data["rows"] for s in row["seats"]}
    lines, unavailable = [], []
    for seat_id in wanted:
        if seat_id not in seats:
            raise ValidationError("Место не относится к залу этого сеанса.")
        row_number, seat = seats[seat_id]
        if seat["is_sold"]:
            unavailable.append(seat_id)
            continue
        lines.append({"seat_id": seat_id, "label": f"ряд {row_number}, место {seat['seat_number']}",
                      "category": "VIP" if seat["seat_type"] == "vip" else "Обычное", "price": price})
    return {"session": data["session"], "lines": lines, "count": len(lines), "total": _money(price * len(lines)),
            "unavailable": unavailable, "open": data["is_open_for_sale"]}


# ------------------------------------------------------------------ продажа

def sell(actor: CurrentUser, session_id, seat_ids, payment_method, client=None, db_path=None) -> dict:
    """Оформление продажи: проверка смены -> оплата -> билеты (одной транзакцией, всё или ничего).

    client: None/пустые поля — «Гость (касса)»; словарь {"full_name", "phone", "email"} или id клиента.
    Возвращает {"sale_id", "total", "payment_method", "tickets": [...]}.
    """
    _desk(actor)
    actor.require(Permission.SELL_TICKET)
    shift = _require_open_shift(actor, db_path)
    if isinstance(client, dict) and not any((client.get(k) or "").strip() for k in ("full_name", "phone", "email")):
        client = None
    if client is None:
        try:
            with transaction(db_path) as conn:
                client = cashier_queries.get_or_create_guest(conn)
        except DBError as exc:
            raise db_error_to_validation(exc) from exc
    created = ticket_service.sell_tickets(actor, session_id, seat_ids, client, db_path,
                                          sale_info={"payment_method": payment_method, "shift_id": shift["id"]})
    return {"sale_id": created[0]["sale_id"], "total": _money(sum(t["price"] for t in created)),
            "payment_method": payment_method, "tickets": created}


# ------------------------------------------------------------------ поиск и возврат

def search_tickets(actor: CurrentUser, ticket_id=None, movie=None, date=None, session_id=None, client=None,
                   status=None, db_path=None) -> list[dict]:
    """Поиск билетов: номер, фильм (часть названия), дата сеанса, номер сеанса, покупатель, статус."""
    _desk(actor)
    found = ticket_service.search_tickets(actor, ticket_id=ticket_id, client=client, session_id=session_id,
                                          date=date, status=status, db_path=db_path)
    needle = (movie or "").strip().casefold()
    return [t for t in found if needle in t["movie_title"].casefold()] if needle else found


def refund_check(actor: CurrentUser, ticket_id, db_path=None) -> dict:
    """Билет и вердикт, можно ли оформить возврат: {"ticket", "can_refund", "reason"}."""
    _desk(actor)
    actor.require(Permission.REFUND_TICKET)
    ticket = ticket_service.get_ticket(actor, ticket_id, db_path)
    reason = ticket["refund_reason"]   # единое правило из ticket_service.refund_block_reason
    if not reason and current_shift(actor, db_path) is None:      # refund() требует открытой смены — вердикт должен совпадать
        reason = _SHIFT_CLOSED_MSG
    return {"ticket": ticket, "can_refund": not reason, "reason": reason}


def refund(actor: CurrentUser, ticket_id, db_path=None) -> dict:
    """Возврат билета (только при открытой смене). Правила и транзакция — в ticket_service.refund_ticket."""
    _desk(actor)
    _require_open_shift(actor, db_path)
    return ticket_service.refund_ticket(actor, ticket_id, db_path)


# ------------------------------------------------------------------ история продаж

def _sale_status(row) -> str:
    if row["tickets_returned"] == 0:
        return "sold"
    return "returned" if row["tickets_sold"] == 0 else "partial"


def list_my_sales(actor: CurrentUser, sale_id=None, date_from=None, date_to=None, movie_id=None, status=None,
                  db_path=None) -> list[dict]:
    """История продаж ТОЛЬКО этого кассира. Фильтры: номер продажи, период, фильм, статус."""
    _desk(actor)

    def blank(value):
        return None if value is None or (isinstance(value, str) and not value.strip()) else value

    sale_id, movie_id, status = blank(sale_id), blank(movie_id), blank(status)
    if sale_id is not None:
        sale_id = parse_int(sale_id, "Номер продажи", 1)
    if status is not None and status not in {k for k, _ in SALE_STATUSES}:
        raise ValidationError("Недопустимый статус продажи.")
    date_from = parse_date(date_from, "Дата с").isoformat() if blank(date_from) is not None else None
    date_to = parse_date(date_to, "Дата по").isoformat() if blank(date_to) is not None else None
    if date_from and date_to and date_from > date_to:
        raise ValidationError("Дата начала периода позже даты окончания.")
    with connection(db_path) as conn:
        rows = cashier_queries.list_sales(conn, actor.id, sale_id, date_from, date_to, movie_id)
    result = []
    for row in rows:
        item = dict(row)
        item["status"] = _sale_status(row)
        item["payment_title"] = PAYMENT_TITLES.get(row["payment_method"], "Не указан")
        if status is None or item["status"] == status:
            result.append(item)
    return result


def get_sale_tickets(actor: CurrentUser, sale_id, db_path=None) -> list[dict]:
    """Билеты своей продажи (полные данные для просмотра и печати)."""
    _desk(actor)
    sale_id = parse_int(sale_id, "Номер продажи", 1)
    with connection(db_path) as conn:
        sale = crud.get_sale(conn, sale_id)
        if sale is None or sale["cashier_id"] != actor.id:
            raise ValidationError("Продажа не найдена.")
        ids = [r["id"] for r in cashier_queries.tickets_of_sale(conn, sale_id)]
    return [ticket_service.get_ticket(actor, i, db_path) for i in ids]


def recent_operations(actor: CurrentUser, limit=RECENT_LIMIT, db_path=None) -> list[dict]:
    """Последние операции кассира: продажи и возвраты вперемешку, новые первыми."""
    _desk(actor)
    with connection(db_path) as conn:
        sales = cashier_queries.list_sales(conn, actor.id)[:limit]
        returns = cashier_queries.recent_returns(conn, actor.id, limit)
    ops = [{"kind": "sale", "number": s["id"], "time": s["created_at"], "movie": s["movie_title"],
            "detail": f"{s['tickets_total']} бил.", "amount": _money(s["total"])} for s in sales]
    ops += [{"kind": "refund", "number": r["id"], "time": r["returned_at"], "movie": r["movie_title"],
             "detail": f"билет №{r['id']}", "amount": -_money(r["price"])} for r in returns]
    return sorted(ops, key=lambda o: (o["time"], o["number"]), reverse=True)[:limit]


# ------------------------------------------------------------------ главная панель

def dashboard(actor: CurrentUser, db_path=None) -> dict:
    """Данные главной панели кассира (только его собственные)."""
    _desk(actor)
    summary = shift_summary(actor, db_path=db_path)
    upcoming = _sellable_sessions(actor, db_path)[:UPCOMING_LIMIT]
    return {
        "now": _stamp(), "name": actor.full_name, "shift": summary["shift"], "summary": summary,
        "upcoming": [{"id": s["id"], "date": s["session_date"], "time": s["session_time"], "movie": s["movie_title"],
                      "hall": s["hall_name"], "free": s["seats_free"], "total": s["seats_total"],
                      "price": s["price"]} for s in upcoming],
        "operations": recent_operations(actor, RECENT_LIMIT, db_path),
    }
