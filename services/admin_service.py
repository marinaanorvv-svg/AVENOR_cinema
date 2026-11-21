"""Сервис администратора: главная панель, расширенный просмотр билетов, отмена сеансов, поиск пользователей.

Это отдельный модуль: функции кассира и покупателя (ticket_service, session_service, ...) он не подменяет, а использует
готовые сервисы там, где они подходят (возврат билета — ticket_service.refund_ticket, отчёты — report_service).
Каждая функция проверяет право через actor.require(...), поэтому защита работает и без интерфейса.
"""
from datetime import datetime, timedelta

from database import admin_queries, crud, report_queries
from database.connection import connection, transaction
from database.errors import DBError

from . import clock
from .auth_service import _ensure_not_last_admin, _get_user_or_fail, _validate_role, _validate_username
from .errors import ValidationError
from .permissions import CurrentUser, Permission, Role
from .session_service import decorate_session
from .ticket_service import _decorate_ticket
from .validators import clean_text, db_error_to_validation, parse_date, parse_int

DASHBOARD_DAYS = 7
DASHBOARD_LIST_SIZE = 8


def _money(value) -> float:
    return round(float(value or 0), 2)


# ------------------------------------------------------------------ главная панель

def dashboard(actor: CurrentUser, db_path=None) -> dict:
    """Все данные главной панели из БД (никаких демонстрационных чисел).

    Выручка считается так же, как в отчётах (кассовый метод): продажи дня минус возвраты дня.
    """
    actor.require(Permission.VIEW_DASHBOARD)
    now = clock.now()
    today = now.date()
    first_day = today - timedelta(days=DASHBOARD_DAYS - 1)
    with connection(db_path) as conn:
        movies_total = admin_queries.count_rows(conn, "movies")
        halls_total = admin_queries.count_rows(conn, "halls")
        users_total = admin_queries.count_rows(conn, "users")
        viewers = admin_queries.count_users_by_role(conn, Role.VIEWER)
        sold_today = admin_queries.tickets_bought_on(conn, today.isoformat())
        returned_today = admin_queries.tickets_returned_on(conn, today.isoformat())
        sales = {r["key"]: r for r in report_queries.cash_flow(conn, "sales", "day", first_day.isoformat(), today.isoformat())}
        refunds = {r["key"]: r for r in report_queries.cash_flow(conn, "refunds", "day", first_day.isoformat(), today.isoformat())}
        sessions = crud.list_sessions_detailed(conn, date_from=(today - timedelta(days=1)).isoformat())
        recent = admin_queries.recent_tickets(conn, DASHBOARD_LIST_SIZE)

    series = []
    for offset in range(DASHBOARD_DAYS):
        day = (first_day + timedelta(days=offset)).isoformat()
        sold, back = sales.get(day), refunds.get(day)
        series.append({"date": day,
                       "tickets": (sold["tickets"] if sold else 0) - (back["tickets"] if back else 0),
                       "revenue": _money((sold["amount"] if sold else 0) - (back["amount"] if back else 0))})

    decorated = [decorate_session(s) for s in sessions]
    active = [s for s in decorated
              if datetime.strptime(f"{s['end_date']} {s['end_time']}", "%Y-%m-%d %H:%M") >= now]
    upcoming = [s for s in decorated if not s["started"]][:DASHBOARD_LIST_SIZE]
    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "movies": movies_total, "active_sessions": len(active), "halls": halls_total,
        "tickets_today": sold_today, "returns_today": returned_today,
        "revenue_today": series[-1]["revenue"], "users": users_total, "viewers": viewers,
        "series": series,
        "upcoming": [{"id": s["id"], "date": s["session_date"], "time": s["session_time"], "movie": s["movie_title"],
                      "hall": s["hall_name"], "sold": s["seats_sold"], "total": s["seats_total"]} for s in upcoming],
        "recent_sales": [{"id": r["id"], "status": r["status"], "bought": r["purchase_date"], "price": r["price"],
                          "movie": r["movie_title"], "client": r["client_name"], "session_date": r["session_date"],
                          "session_time": r["session_time"],
                          "seat": f"ряд {r['row_number']}, место {r['seat_number']}"} for r in recent],
    }


# ------------------------------------------------------------------ билеты

def search_tickets(actor: CurrentUser, ticket_id=None, client=None, movie_id=None, status=None,
                   session_from=None, session_to=None, bought_from=None, bought_to=None, db_path=None) -> list[dict]:
    """Просмотр и поиск всех билетов: по номеру, покупателю, фильму, статусу, датам сеанса и покупки."""
    actor.require(Permission.VIEW_ALL_TICKETS)

    def blank(value):
        return None if value is None or (isinstance(value, str) and not value.strip()) else value

    ticket_id, movie_id, status = blank(ticket_id), blank(movie_id), blank(status)
    if ticket_id is not None:
        ticket_id = parse_int(ticket_id, "Номер билета", 1)
    if movie_id is not None:
        movie_id = parse_int(movie_id, "Фильм", 1)
    if status is not None and status not in ("sold", "returned"):
        raise ValidationError("Статус: sold (продан) или returned (возвращён).")
    dates = {}
    for key, value, label in (("session_from", session_from, "Сеанс с"), ("session_to", session_to, "Сеанс по"),
                              ("bought_from", bought_from, "Куплен с"), ("bought_to", bought_to, "Куплен по")):
        dates[key] = parse_date(value, label).isoformat() if blank(value) is not None else None
    for a, b, label in (("session_from", "session_to", "сеанса"), ("bought_from", "bought_to", "покупки")):
        if dates[a] and dates[b] and dates[a] > dates[b]:
            raise ValidationError(f"Период даты {label}: начало позже конца.")
    with connection(db_path) as conn:
        rows = admin_queries.list_tickets_admin(conn, ticket_id, movie_id, status, **dates)
    tickets = []
    for row in rows:
        item = _decorate_ticket(row)
        item["seller_label"] = row["seller_name"] or "—"
        item["session_cancelled"] = bool(row["is_cancelled"])
        tickets.append(item)
    needle = client.strip().casefold() if isinstance(client, str) else ""
    if needle:
        digits = "".join(ch for ch in needle if ch.isdigit())

        def matches(t):
            phone = "".join(ch for ch in (t["client_phone"] or "") if ch.isdigit())
            return (needle in t["client_name"].casefold() or needle in (t["client_email"] or "").casefold()
                    or (len(digits) >= 3 and digits in phone))
        tickets = [t for t in tickets if matches(t)]
    return tickets


# ------------------------------------------------------------------ сеансы

def list_sessions(actor: CurrentUser, date_from=None, date_to=None, hall_id=None, movie_id=None,
                  include_cancelled=True, db_path=None) -> list[dict]:
    """Расписание для администратора: фильтры по датам, фильму и залу; отменённые сеансы помечены."""
    actor.require(Permission.MANAGE_SESSIONS)
    date_from = parse_date(date_from, "Дата с").isoformat() if date_from not in (None, "") else None
    date_to = parse_date(date_to, "Дата по").isoformat() if date_to not in (None, "") else None
    if date_from and date_to and date_from > date_to:
        raise ValidationError("Дата начала периода позже даты окончания.")
    with connection(db_path) as conn:
        rows = crud.list_sessions_detailed(conn, date_from, date_to, hall_id, movie_id,
                                           include_cancelled=include_cancelled)
    result = []
    for row in rows:
        item = decorate_session(row)
        item["cancelled"] = bool(row["is_cancelled"])
        result.append(item)
    return result


def cancel_session(actor: CurrentUser, session_id, db_path=None) -> dict:
    """Отмена сеанса с учётом продаж.

    До начала сеанса: все действующие билеты возвращаются (статус «returned», возврат попадает в отчёты в день
    отмены), сеанс помечается отменённым и исчезает из афиши и продажи. История билетов сохраняется.
    Начавшийся сеанс отменить нельзя. Возвращает {"refunded": штук, "amount": сумма}.
    """
    actor.require(Permission.MANAGE_SESSIONS)
    session_id = parse_int(session_id, "Сеанс", 1)
    try:
        with transaction(db_path) as conn:
            session = crud.get_session(conn, session_id)
            if session is None:
                raise ValidationError("Сеанс не найден.")
            if session["is_cancelled"]:
                raise ValidationError("Сеанс уже отменён.")
            start = datetime.strptime(f"{session['session_date']} {session['session_time']}", "%Y-%m-%d %H:%M")
            if clock.now() >= start:
                raise ValidationError("Сеанс уже начался: отменить его нельзя.")
            stamp = clock.now().strftime("%Y-%m-%d %H:%M:%S")
            sold = admin_queries.sold_tickets_of_session(conn, session_id)
            for ticket in sold:
                crud.update_ticket(conn, ticket["id"], status="returned", returned_at=stamp)
            crud.update_session(conn, session_id, is_cancelled=1)
            return {"refunded": len(sold), "amount": _money(sum(t["price"] for t in sold))}
    except DBError as exc:
        raise db_error_to_validation(exc) from exc


# ------------------------------------------------------------------ жанры

def list_genres_with_counts(actor: CurrentUser, db_path=None) -> list[dict]:
    """Жанры с числом фильмов в каждом (для раздела «Фильмы и жанры»)."""
    actor.require(Permission.MANAGE_GENRES)
    with connection(db_path) as conn:
        genres = [dict(g) for g in crud.list_genres(conn)]
        counts = admin_queries.genre_movie_counts(conn)
    for genre in genres:
        genre["movies"] = counts.get(genre["id"], 0)
    return sorted(genres, key=lambda g: g["name"].casefold())


# ------------------------------------------------------------------ пользователи

def list_users(actor: CurrentUser, search=None, role=None, active=None, db_path=None) -> list[dict]:
    """Пользователи без хешей паролей; поиск по логину и ФИО, фильтры по роли и статусу."""
    actor.require(Permission.MANAGE_USERS)
    if role not in (None, "") and role not in Role.ALL:
        raise ValidationError("Недопустимая роль.")
    with connection(db_path) as conn:
        users = [dict(u) for u in crud.list_users(conn)]
    needle = (search or "").strip().casefold()
    result = []
    for user in users:
        user.pop("password_hash", None)
        if needle and needle not in user["username"].casefold() and needle not in user["full_name"].casefold():
            continue
        if role and user["role"] != role:
            continue
        if active is not None and bool(user["is_active"]) != bool(active):
            continue
        result.append(user)
    return sorted(result, key=lambda u: u["username"].casefold())


def update_user_profile(actor: CurrentUser, user_id, username, full_name, db_path=None) -> None:
    """Правка логина и ФИО. Пароль и роль меняются отдельными действиями."""
    actor.require(Permission.MANAGE_USERS)
    username = _validate_username(username)
    full_name = clean_text(full_name, "ФИО", 100)
    try:
        with transaction(db_path) as conn:
            _get_user_or_fail(conn, user_id)
            crud.update_user(conn, user_id, username=username, full_name=full_name)
    except DBError as exc:
        raise db_error_to_validation(exc, "Пользователь с таким логином уже существует.") from exc


def assign_role(actor: CurrentUser, user_id, new_role, db_path=None) -> None:
    """Назначение роли с защитой от потери доступа.

    Нельзя менять собственную роль и понижать последнего активного администратора. Если пользователь становится
    покупателем и у него нет клиентской карточки, она создаётся — иначе он не увидит «Мои билеты» и не сможет покупать.
    """
    actor.require(Permission.MANAGE_USERS)
    _validate_role(new_role)
    try:
        with transaction(db_path) as conn:
            user = _get_user_or_fail(conn, user_id)
            if user_id == actor.id and new_role != user["role"]:
                raise ValidationError("Нельзя изменить собственную роль.")
            if new_role != Role.ADMIN:
                _ensure_not_last_admin(conn, user)
            fields = {"role": new_role}
            if new_role == Role.VIEWER and user["client_id"] is None:
                fields["client_id"] = crud.create_client(conn, user["full_name"])
            crud.update_user(conn, user_id, **fields)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc
