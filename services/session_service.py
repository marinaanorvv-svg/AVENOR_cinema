"""Сеансы и расписание."""
from datetime import datetime, timedelta

from database import crud
from database.connection import connection, transaction
from database.errors import DBError

from . import clock
from .errors import ValidationError
from .permissions import CurrentUser, Permission
from .validators import db_error_to_validation, parse_date, parse_int, parse_price, parse_time

CLEANING_BREAK_MIN = 15   # перерыв между сеансами в одном зале (уборка, посадка зрителей)
_EDITABLE_FIELDS = {"movie_id", "hall_id", "session_date", "session_time", "price"}
_BUSY_SLOT_MSG = "В этом зале уже есть сеанс на это время."


def _now() -> datetime:
    """Текущее время (через services.clock — в тестах подменяется)."""
    return clock.now()


def _start_of(date_str: str, time_str: str) -> datetime:
    return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")


def _end_of(start: datetime, duration_min: int) -> datetime:
    return start + timedelta(minutes=duration_min)


def decorate_session(row) -> dict:
    """Добавляет к строке из БД вычисляемые поля для GUI."""
    item = dict(row)
    start = _start_of(item["session_date"], item["session_time"])
    end = _end_of(start, item["duration"])
    item["end_time"] = end.strftime("%H:%M")          # может быть уже после полуночи
    item["end_date"] = end.date().isoformat()         # а тогда это уже следующий день
    item["started"] = start <= _now()                  # сеанс уже начался: билеты не продаются
    item["seats_total"] = item["hall_capacity"]
    item["seats_sold"] = item["sold_count"]
    item["seats_free"] = item["hall_capacity"] - item["sold_count"]
    return item


# ------------------------------------------------------------------ проверки

def _clean_fields(conn, fields: dict) -> dict:
    """Проверяет и нормализует переданные поля (даты — в ISO, время — 'ЧЧ:ММ')."""
    unknown = set(fields) - _EDITABLE_FIELDS
    if unknown:
        raise ValidationError(f"Неизвестные поля: {', '.join(sorted(unknown))}.")
    clean = {}
    if "movie_id" in fields:
        movie_id = parse_int(fields["movie_id"], "Фильм", 1)
        if crud.get_movie(conn, movie_id) is None:
            raise ValidationError("Выбранный фильм не существует.")
        clean["movie_id"] = movie_id
    if "hall_id" in fields:
        hall_id = parse_int(fields["hall_id"], "Зал", 1)
        if crud.get_hall(conn, hall_id) is None:
            raise ValidationError("Выбранный зал не существует.")
        clean["hall_id"] = hall_id
    if "session_date" in fields:
        clean["session_date"] = parse_date(fields["session_date"]).isoformat()
    if "session_time" in fields:
        clean["session_time"] = parse_time(fields["session_time"]).strftime("%H:%M")
    if "price" in fields:
        clean["price"] = parse_price(fields["price"])
    return clean


def _ensure_hall_free(conn, hall_id, start: datetime, duration_min: int, exclude_id=None):
    """В зале не должно быть пересекающихся сеансов (с учётом перерыва).

    Каждый сеанс занимает зал на [начало; начало + длительность + перерыв).
    Два интервала пересекаются, если каждый начинается раньше конца другого.
    Берём сеансы за соседние сутки: фильм может закончиться после полуночи.
    """
    day = start.date()
    neighbours = crud.list_sessions_detailed(
        conn, date_from=(day - timedelta(days=1)).isoformat(),
        date_to=(day + timedelta(days=1)).isoformat(), hall_id=hall_id)
    new_end = _end_of(start, duration_min + CLEANING_BREAK_MIN)
    for other in neighbours:
        if other["id"] == exclude_id:
            continue
        other_start = _start_of(other["session_date"], other["session_time"])
        other_end = _end_of(other_start, other["duration"] + CLEANING_BREAK_MIN)
        if start < other_end and other_start < new_end:
            shown_end = _end_of(other_start, other["duration"]).strftime("%H:%M")
            raise ValidationError(
                f"Зал занят: сеанс «{other['movie_title']}» "
                f"{other['session_date']} {other['session_time']}–{shown_end}. "
                f"Между сеансами нужен перерыв {CLEANING_BREAK_MIN} мин.")


def _ensure_schedule_ok(conn, movie_id, hall_id, date_str, time_str, exclude_id=None,
                        check_past=True, check_overlap=True):
    start = _start_of(date_str, time_str)
    if check_past and start < _now():
        raise ValidationError("Нельзя назначить сеанс на прошедшее время.")
    if check_overlap:
        movie = crud.get_movie(conn, movie_id)
        _ensure_hall_free(conn, hall_id, start, movie["duration"], exclude_id)


def _get_or_fail(conn, session_id):
    session = crud.get_session(conn, session_id)
    if session is None:
        raise ValidationError("Сеанс не найден.")
    return session


# ------------------------------------------------------------------ чтение

def list_sessions(actor: CurrentUser, date=None, date_from=None, date_to=None,
                  hall_id=None, movie_id=None, db_path=None) -> list[dict]:
    """Расписание. `date` — один день; `date_from`/`date_to` — период."""
    actor.require(Permission.VIEW_SCHEDULE)
    if date is not None:
        date_from = date_to = date
    date_from = parse_date(date_from, "Дата с").isoformat() if date_from is not None else None
    date_to = parse_date(date_to, "Дата по").isoformat() if date_to is not None else None
    with connection(db_path) as conn:
        rows = crud.list_sessions_detailed(conn, date_from, date_to, hall_id, movie_id)
    return [decorate_session(r) for r in rows]


def get_session(actor: CurrentUser, session_id: int, db_path=None) -> dict:
    actor.require(Permission.VIEW_SCHEDULE)
    with connection(db_path) as conn:
        row = crud.get_session_detailed(conn, session_id)
    if row is None:
        raise ValidationError("Сеанс не найден.")
    return decorate_session(row)


def get_schedule_for_date(actor: CurrentUser, date, db_path=None) -> list[dict]:
    """Афиша на день: фильмы со списком их сеансов.

    [{"movie": {id, title, genre_name, duration, age_rating, description, poster_path},
      "sessions": [{id, session_time, end_time, hall_name, price, seats_free, seats_total}]}]
    """
    sessions = list_sessions(actor, date=date, db_path=db_path)
    grouped: dict[int, dict] = {}
    for s in sessions:  # уже отсортированы по времени
        entry = grouped.setdefault(s["movie_id"], {
            "movie": {"id": s["movie_id"], "title": s["movie_title"], "genre_name": s["genre_name"],
                      "duration": s["duration"], "age_rating": s["age_rating"],
                      "description": s["description"], "poster_path": s["poster_path"]},
            "sessions": []})
        entry["sessions"].append({
            "id": s["id"], "session_date": s["session_date"], "session_time": s["session_time"],
            "end_time": s["end_time"], "end_date": s["end_date"], "started": s["started"],
            "hall_name": s["hall_name"], "price": s["price"],
            "seats_free": s["seats_free"], "seats_total": s["seats_total"]})
    return sorted(grouped.values(), key=lambda e: e["movie"]["title"].casefold())


# ------------------------------------------------------------------ изменение

def create_session(actor: CurrentUser, movie_id, hall_id, session_date, session_time, price,
                   db_path=None) -> int:
    actor.require(Permission.MANAGE_SESSIONS)
    try:
        with transaction(db_path) as conn:
            clean = _clean_fields(conn, {"movie_id": movie_id, "hall_id": hall_id,
                                         "session_date": session_date,
                                         "session_time": session_time, "price": price})
            _ensure_schedule_ok(conn, clean["movie_id"], clean["hall_id"],
                                clean["session_date"], clean["session_time"])
            return crud.create_session(conn, **clean)
    except DBError as exc:
        raise db_error_to_validation(exc, _BUSY_SLOT_MSG) from exc


def update_session(actor: CurrentUser, session_id: int, db_path=None, **fields) -> None:
    """Частичное обновление: update_session(actor, 7, price=400, session_time="19:30").

    Правила целостности:
      - есть проданные билеты -> сеанс менять нельзя (сначала оформить возвраты);
      - есть только возвращённые билеты -> нельзя менять зал и цену
        (иначе исказится история и отчёты), остальное можно.
    """
    actor.require(Permission.MANAGE_SESSIONS)
    try:
        with transaction(db_path) as conn:
            current = _get_or_fail(conn, session_id)
            if current["is_cancelled"]:
                raise ValidationError("Сеанс отменён: изменить его нельзя.")
            clean = _clean_fields(conn, fields)
            changed = {k: v for k, v in clean.items() if current[k] != v}
            if not changed:
                return

            sold = crud.count_tickets_by_session(conn, session_id, "sold")
            if sold:
                raise ValidationError(
                    f"Нельзя изменить сеанс: на него проданы билеты ({sold}). "
                    "Сначала оформите их возврат.")
            if crud.count_tickets_by_session(conn, session_id) and ({"hall_id", "price"} & changed.keys()):
                raise ValidationError(
                    "Нельзя изменить зал или цену: по сеансу уже оформлялись билеты.")

            merged = {**dict(current), **changed}
            _ensure_schedule_ok(
                conn, merged["movie_id"], merged["hall_id"],
                merged["session_date"], merged["session_time"], exclude_id=session_id,
                check_past=bool({"session_date", "session_time"} & changed.keys()),
                check_overlap=bool({"movie_id", "hall_id", "session_date", "session_time"} & changed.keys()))
            crud.update_session(conn, session_id, **changed)
    except DBError as exc:
        raise db_error_to_validation(exc, _BUSY_SLOT_MSG) from exc


def delete_session(actor: CurrentUser, session_id: int, db_path=None) -> None:
    """Удаляет сеанс, только если по нему не оформлялось ни одного билета
    (историю продаж и возвратов для отчётов нужно сохранять)."""
    actor.require(Permission.MANAGE_SESSIONS)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, session_id)
            if crud.count_tickets_by_session(conn, session_id):
                raise ValidationError(
                    "Нельзя удалить сеанс: по нему оформлялись билеты (включая возвращённые).")
            crud.delete_session(conn, session_id)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc


# ------------------------------------------------------------------ автоматическое расписание

SLOT_TIMES = ("10:00", "12:30", "15:00", "17:30", "20:00", "22:30")   # удобные времена начала сеансов


def auto_schedule(actor: CurrentUser, movie_id, date_from, days=7, per_day=2, price=350, db_path=None) -> dict:
    """Сама расставляет сеансы фильма на несколько дней — администратору не нужно выбирать зал и время.

    Для каждого дня берутся ближайшие удобные времена (SLOT_TIMES) и первый зал, где в это время свободно
    (с учётом длительности фильма и перерыва). Прошедшее время и занятые залы пропускаются.
    Возвращает {"created": сколько сеансов добавлено, "skipped": сколько мест в расписании не нашлось}.
    """
    actor.require(Permission.MANAGE_SESSIONS)
    days = parse_int(days, "Дней", 1, 31)
    per_day = parse_int(per_day, "Сеансов в день", 1, len(SLOT_TIMES))
    first_day = parse_date(date_from, "Дата начала")
    with connection(db_path) as conn:
        halls = [dict(h) for h in crud.list_halls(conn)]
    if not halls:
        raise ValidationError("Сначала добавьте хотя бы один зал.")
    created = skipped = 0
    for offset in range(days):
        day = (first_day + timedelta(days=offset)).isoformat()
        placed = 0
        for time_text in SLOT_TIMES:
            if placed >= per_day:
                break
            for shift in range(len(halls)):          # залы по кругу: нагрузка делится между ними
                hall = halls[(offset + placed + shift) % len(halls)]
                try:
                    create_session(actor, movie_id, hall["id"], day, time_text, price, db_path=db_path)
                except ValidationError:
                    continue
                placed += 1
                created += 1
                break
        skipped += per_day - placed
    return {"created": created, "skipped": skipped}
