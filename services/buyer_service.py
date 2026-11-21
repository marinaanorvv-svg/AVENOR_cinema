"""Личный кабинет покупателя: афиша, страница фильма, заказ с тестовой оплатой, билеты, история покупок, профиль.

Все функции требуют право USE_PORTAL (есть только у роли «покупатель») и учётную запись, привязанную к клиенту.
Покупка и возврат используют общую логику ticket_service (те же транзакции и правила, что и у кассы),
поэтому операции покупателя и кассира не противоречат друг другу.
"""
import re
from datetime import datetime, timedelta

from database import buyer_queries, crud
from database.connection import connection, transaction
from database.errors import DBError

from . import clock, movie_service, session_service, ticket_service
from .errors import PermissionDenied, ValidationError
from .permissions import CurrentUser, Permission
from .validators import clean_text, db_error_to_validation, normalize_email, normalize_phone, parse_date, parse_int

DAYS_AHEAD = 30            # на сколько дней вперёд показываем сеансы
HOME_LIMIT = 8             # карточек в каждой подборке на главной
NEW_LIMIT = 6              # «Новинки»: последние добавленные в афишу фильмы
PAYMENT_TITLE = "Банковская карта (тестовая оплата)"
ORDER_STATUSES = (("paid", "Оформлен"), ("partial", "Частично возвращён"), ("returned", "Возвращён"))
TICKET_GROUPS = (("upcoming", "Предстоящие"), ("past", "Прошедшие"), ("returned", "Возвращённые"))
SORTS = (("title", "По названию (А–Я)"), ("title_desc", "По названию (Я–А)"), ("popular", "По популярности"))


def _portal(actor: CurrentUser, need_client: bool = True) -> None:
    """Право на кабинет; need_client — для всего, что связано с билетами, заказами и покупкой.
    Просматривать афишу и профиль можно и без привязки к клиенту (как раньше смотрели расписание)."""
    actor.require(Permission.USE_PORTAL)
    if need_client and actor.client_id is None:
        raise ValidationError("Учётная запись не привязана к покупателю: покупки и билеты недоступны.")


def _now() -> datetime:
    return clock.now()


# ------------------------------------------------------------------ афиша

def _upcoming_sessions(actor, db_path) -> list[dict]:
    today = _now().date()
    sessions = session_service.list_sessions(actor, date_from=today.isoformat(),
                                             date_to=(today + timedelta(days=DAYS_AHEAD)).isoformat(), db_path=db_path)
    return [s for s in sessions if not s["started"]]


def catalog(actor: CurrentUser, search=None, genre=None, age=None, sort="title", day=None, db_path=None) -> list[dict]:
    """Фильмы, на которые сейчас можно купить билет (есть неначавшийся сеанс; отменённые не учитываются).

    Поля: данные фильма, sessions (число сеансов), next_date/next_time, min_price, popularity, is_new.
    day — дата ISO: оставляет только фильмы с сеансами в этот день (сеансы, цена и «ближайший» считаются за день).
    """
    _portal(actor, need_client=False)
    sessions = _upcoming_sessions(actor, db_path)
    if day:
        day = parse_date(day, "Дата").isoformat()
        sessions = [s for s in sessions if s["session_date"] == day]
    with connection(db_path) as conn:
        popular = buyer_queries.popularity(conn)
    movies: dict[int, dict] = {}
    for s in sessions:       # отсортированы по дате и времени, поэтому первый сеанс — ближайший
        m = movies.setdefault(s["movie_id"], {
            "id": s["movie_id"], "title": s["movie_title"], "genre_name": s["genre_name"], "duration": s["duration"],
            "age_rating": s["age_rating"], "description": s["description"], "poster_path": s["poster_path"],
            "sessions": 0, "next_date": s["session_date"], "next_time": s["session_time"],
            "min_price": s["price"], "popularity": popular.get(s["movie_id"], 0), "is_new": False})
        m["sessions"] += 1
        m["min_price"] = min(m["min_price"], s["price"])
    newest = sorted(movies, reverse=True)[:NEW_LIMIT]      # чем больше номер, тем позже фильм добавлен в афишу
    for movie_id in newest:
        movies[movie_id]["is_new"] = True
    result = list(movies.values())
    needle = (search or "").strip().casefold()
    if needle:
        result = [m for m in result if needle in m["title"].casefold()]
    if genre:
        result = [m for m in result if m["genre_name"] == genre]
    if age:
        result = [m for m in result if m["age_rating"] == age]
    if sort == "popular":
        result.sort(key=lambda m: (-m["popularity"], m["title"].casefold()))
    else:
        result.sort(key=lambda m: m["title"].casefold(), reverse=(sort == "title_desc"))
    return result


def catalog_days(actor: CurrentUser, limit=7, db_path=None) -> list[str]:
    """Ближайшие даты (ISO), в которые есть неначавшиеся сеансы: для кнопок «Сегодня», «Завтра» и т. д."""
    _portal(actor, need_client=False)
    return sorted({s["session_date"] for s in _upcoming_sessions(actor, db_path)})[:limit]


def catalog_filters(actor: CurrentUser, db_path=None) -> dict:
    """Значения для фильтров афиши: жанры и возрастные ограничения тех фильмов, что сейчас в афише."""
    movies = catalog(actor, db_path=db_path)
    return {"genres": sorted({m["genre_name"] for m in movies}, key=str.casefold),
            "ages": sorted({m["age_rating"] for m in movies}, key=lambda a: (len(a), a))}


def home(actor: CurrentUser, db_path=None) -> dict:
    """Данные главной страницы: приветствие, афиша, популярное, новинки, ближайший билет."""
    _portal(actor, need_client=False)
    movies = catalog(actor, db_path=db_path)
    popular = sorted((m for m in movies if m["popularity"] > 0), key=lambda m: (-m["popularity"], m["title"].casefold()))
    new = sorted((m for m in movies if m["is_new"]), key=lambda m: -m["id"])
    tickets = my_tickets(actor, "upcoming", db_path) if actor.client_id is not None else []
    soonest = min(tickets, key=lambda t: (t["session_date"], t["session_time"])) if tickets else None
    return {"name": actor.full_name, "now_showing": movies[:HOME_LIMIT], "popular": popular[:HOME_LIMIT],
            "new": new[:HOME_LIMIT], "upcoming_tickets": len(tickets), "next_ticket": soonest}


def movie_page(actor: CurrentUser, movie_id, db_path=None) -> dict:
    """Страница фильма: данные + доступные даты и сеансы (только не начавшиеся и не отменённые)."""
    _portal(actor, need_client=False)
    movie = movie_service.get_movie(actor, parse_int(movie_id, "Фильм", 1), db_path)
    days: dict[str, list[dict]] = {}
    for s in _upcoming_sessions(actor, db_path):
        if s["movie_id"] == movie["id"]:
            days.setdefault(s["session_date"], []).append(s)
    return {"movie": movie, "days": days}


# ------------------------------------------------------------------ места, оплата, заказ

def quote(actor: CurrentUser, session_id, seat_ids, db_path=None) -> dict:
    """Актуальная проверка выбранных мест и стоимость.

    {"session", "lines": [{seat_id, label, category, price}], "count", "total", "unavailable": [seat_id], "open"}.
    Места, купленные другим покупателем или кассиром, попадают в "unavailable" и в стоимость не входят.
    """
    _portal(actor)
    data = ticket_service.get_session_seat_map(actor, session_id, db_path)
    session = data["session"]
    price = float(session["price"])
    seats = {s["id"]: (row["row_number"], s) for row in data["rows"] for s in row["seats"]}
    lines, unavailable = [], []
    for seat_id in dict.fromkeys(seat_ids):
        if seat_id not in seats:
            raise ValidationError("Место не относится к залу этого сеанса.")
        row_number, seat = seats[seat_id]
        if seat["is_sold"]:
            unavailable.append(seat_id)
            continue
        lines.append({"seat_id": seat_id, "label": f"ряд {row_number}, место {seat['seat_number']}",
                      "category": "VIP" if seat["seat_type"] == "vip" else "Обычное", "price": price})
    return {"session": session, "lines": lines, "count": len(lines), "total": round(price * len(lines), 2),
            "unavailable": unavailable, "open": data["is_open_for_sale"] and not session.get("is_cancelled")}


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, ch in enumerate(reversed(digits)):
        n = int(ch)
        if index % 2:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


def validate_card(number, holder, expiry, cvc, today=None) -> None:
    """Проверка данных тестовой оплаты. Номер карты нигде не сохраняется."""
    digits = re.sub(r"[\s-]", "", number or "")
    if not re.fullmatch(r"\d{16}", digits) or not _luhn_ok(digits):
        raise ValidationError("Номер карты введён неверно: нужно 16 цифр.")
    if not re.fullmatch(r"[A-Za-z ]{2,40}", (holder or "").strip()):
        raise ValidationError("Имя владельца укажите латиницей, как на карте.")
    match = re.fullmatch(r"(\d{2})\s*/\s*(\d{2})", (expiry or "").strip())
    if not match or not 1 <= int(match.group(1)) <= 12:
        raise ValidationError("Срок действия укажите в формате ММ/ГГ.")
    today = today or _now().date()
    if (2000 + int(match.group(2)), int(match.group(1))) < (today.year, today.month):
        raise ValidationError("Срок действия карты истёк.")
    if not re.fullmatch(r"\d{3}", (cvc or "").strip()):
        raise ValidationError("CVC — три цифры.")


def place_order(actor: CurrentUser, session_id, seat_ids, card: dict, db_path=None) -> dict:
    """Оформление заказа: проверка карты -> заказ и билеты одной транзакцией (всё или ничего).

    card — {"number", "holder", "expiry", "cvc"}. Возвращает {"order_id", "total", "tickets"}.
    """
    _portal(actor)
    card = card or {}
    validate_card(card.get("number"), card.get("holder"), card.get("expiry"), card.get("cvc"))
    tickets = ticket_service.sell_tickets(actor, session_id, seat_ids, actor.client_id, db_path,
                                          order_info={"payment_method": "card"})
    return {"order_id": tickets[0]["order_id"], "total": round(sum(t["price"] for t in tickets), 2), "tickets": tickets}


# ------------------------------------------------------------------ мои билеты и возврат

def _group(ticket: dict) -> str:
    if ticket["status"] == ticket_service.RETURNED:
        return "returned"
    return "past" if ticket["session_started"] else "upcoming"


def my_tickets(actor: CurrentUser, group=None, db_path=None) -> list[dict]:
    """Собственные билеты с группой (upcoming/past/returned) и постером. Предстоящие — по возрастанию даты."""
    _portal(actor)
    if group is not None and group not in dict(TICKET_GROUPS):
        raise ValidationError("Неизвестная группа билетов.")
    tickets = ticket_service.list_my_tickets(actor, db_path)
    with connection(db_path) as conn:
        posters = buyer_queries.posters_for_sessions(conn, [t["session_id"] for t in tickets])
    for t in tickets:
        t["group"] = _group(t)
        t["movie_id"], t["poster_path"] = posters.get(t["session_id"], (None, None))
    if group:
        tickets = [t for t in tickets if t["group"] == group]
    return sorted(tickets, key=lambda t: (t["session_date"], t["session_time"]), reverse=group != "upcoming")


def refund_check(actor: CurrentUser, ticket_id, db_path=None) -> dict:
    """Собственный билет и вердикт: {"ticket", "can_refund", "reason"}. Чужой билет — PermissionDenied."""
    _portal(actor)
    ticket = ticket_service.get_ticket(actor, ticket_id, db_path)
    reason = ticket["refund_reason"]   # единое правило из ticket_service.refund_block_reason
    return {"ticket": ticket, "can_refund": not reason, "reason": reason}


def refund(actor: CurrentUser, ticket_id, db_path=None) -> dict:
    _portal(actor)
    return ticket_service.refund_own_ticket(actor, ticket_id, db_path)


# ------------------------------------------------------------------ история покупок

def _order_status(row) -> str:
    if row["tickets_returned"] == 0:
        return "paid"
    return "returned" if row["tickets_sold"] == 0 else "partial"


def list_my_orders(actor: CurrentUser, order_id=None, date_from=None, date_to=None, status=None, db_path=None) -> list[dict]:
    """Заказы ТОЛЬКО этого покупателя. Фильтры: номер заказа, период (по дате покупки), статус."""
    _portal(actor)

    def blank(value):
        return None if value is None or (isinstance(value, str) and not value.strip()) else value

    order_id, date_from, date_to, status = map(blank, (order_id, date_from, date_to, status))
    if order_id is not None:
        order_id = parse_int(order_id, "Номер заказа", 1)
    if date_from is not None:
        date_from = parse_date(date_from, "Дата «с»").isoformat()
    if date_to is not None:
        date_to = parse_date(date_to, "Дата «по»").isoformat()
    if date_from and date_to and date_from > date_to:
        raise ValidationError("Дата «с» не может быть позже даты «по».")
    if status is not None and status not in dict(ORDER_STATUSES):
        raise ValidationError("Неизвестный статус заказа.")
    with connection(db_path) as conn:
        rows = buyer_queries.list_orders(conn, actor.id, order_id, date_from, date_to)
    orders = []
    for row in rows:
        item = dict(row)
        item["status"] = _order_status(row)
        item["payment_title"] = PAYMENT_TITLE if row["payment_method"] == "card" else "Не указан"
        orders.append(item)
    return [o for o in orders if status is None or o["status"] == status]


def get_order_tickets(actor: CurrentUser, order_id, db_path=None) -> list[dict]:
    """Билеты своего заказа. Чужой заказ — PermissionDenied."""
    _portal(actor)
    order_id = parse_int(order_id, "Номер заказа", 1)
    with connection(db_path) as conn:
        order = crud.get_order(conn, order_id)
        if order is None:
            raise ValidationError("Заказ не найден.")
        if order["user_id"] != actor.id:
            raise PermissionDenied("Недостаточно прав для просмотра этого заказа.")
        ids = buyer_queries.order_ticket_ids(conn, order_id)
    tickets = [ticket_service.get_ticket(actor, i, db_path) for i in ids]
    with connection(db_path) as conn:
        posters = buyer_queries.posters_for_sessions(conn, [t["session_id"] for t in tickets])
    for t in tickets:
        t["movie_id"], t["poster_path"] = posters.get(t["session_id"], (None, None))
    return tickets


# ------------------------------------------------------------------ профиль

def get_profile(actor: CurrentUser, db_path=None) -> dict:
    _portal(actor, need_client=False)
    with connection(db_path) as conn:
        row = buyer_queries.profile_row(conn, actor.id)
    if row is None:
        raise ValidationError("Учётная запись не найдена.")
    return dict(row)


def update_profile(actor: CurrentUser, full_name, phone, email, db_path=None) -> dict:
    """Изменение собственных данных (ФИО, телефон, email) в профиле и в карточке клиента, к которой привязаны билеты."""
    _portal(actor)
    full_name = clean_text(full_name, "ФИО", 100)
    phone, email = normalize_phone(phone), normalize_email(email)
    try:
        with transaction(db_path) as conn:
            for found, label in ((phone and crud.get_client_by_phone(conn, phone), "телефоном"),
                                 (email and crud.get_client_by_email(conn, email), "email")):
                if found and found["id"] != actor.client_id:
                    raise ValidationError(f"Клиент с таким {label} уже зарегистрирован.")
            crud.update_client(conn, actor.client_id, full_name=full_name, phone=phone, email=email)
            crud.update_user(conn, actor.id, full_name=full_name)
    except DBError as exc:
        raise db_error_to_validation(exc, "Такие данные уже используются.") from exc
    return get_profile(actor, db_path)
