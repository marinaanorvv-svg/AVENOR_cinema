"""Залы и схема мест."""
import re

from database import crud
from database.connection import connection, transaction
from database.errors import DBError

from .errors import ValidationError
from .permissions import CurrentUser, Permission
from .validators import clean_text, db_error_to_validation, parse_int

MAX_ROWS = 30
MAX_SEATS_PER_ROW = 40
SEAT_TYPES = ("regular", "vip")
_DUPLICATE_MSG = "Зал с таким названием уже существует."


# ------------------------------------------------------------------ вспомогательное

def _parse_vip_rows(vip_rows, rows: int) -> set[int]:
    """VIP-ряды: список чисел или строка из поля ввода вида «4, 5»."""
    if vip_rows is None or vip_rows == "":
        return set()
    if isinstance(vip_rows, str):
        vip_rows = [token for token in re.split(r"[,\s;]+", vip_rows.strip()) if token]
    return {parse_int(item, "VIP-ряд", 1, rows) for item in vip_rows}


def _build_seats(rows: int, seats_per_row: int, vip_rows: set[int]):
    """Прямоугольная схема: (ряд, место, тип) для каждого места зала."""
    return [(row, number, "vip" if row in vip_rows else "regular")
            for row in range(1, rows + 1)
            for number in range(1, seats_per_row + 1)]


def _validate_layout(rows, seats_per_row, vip_rows):
    rows = parse_int(rows, "Количество рядов", 1, MAX_ROWS)
    seats_per_row = parse_int(seats_per_row, "Мест в ряду", 1, MAX_SEATS_PER_ROW)
    return rows, seats_per_row, _parse_vip_rows(vip_rows, rows)


def _validate_seat_type(seat_type) -> str:
    if seat_type not in SEAT_TYPES:
        raise ValidationError("Тип места: regular (обычное) или vip.")
    return seat_type


def _ensure_name_free(conn, name, exclude_id=None):
    """Уникальность названия без учёта регистра (проверка в Python, см. genre_service)."""
    for hall in crud.list_halls(conn):
        if hall["id"] != exclude_id and hall["name"].casefold() == name.casefold():
            raise ValidationError(_DUPLICATE_MSG)


def _get_or_fail(conn, hall_id):
    hall = crud.get_hall(conn, hall_id)
    if hall is None:
        raise ValidationError("Зал не найден.")
    return hall


def _ensure_no_sessions(conn, hall_id, action: str):
    count = crud.count_sessions_by_hall(conn, hall_id)
    if count:
        raise ValidationError(f"Нельзя {action}: в зале есть сеансы ({count}). Сначала удалите сеансы.")


# ------------------------------------------------------------------ чтение

def list_halls(actor: CurrentUser, db_path=None) -> list[dict]:
    actor.require(Permission.VIEW_SCHEDULE)
    with connection(db_path) as conn:
        halls = [dict(h) for h in crud.list_halls(conn)]
    return sorted(halls, key=lambda h: h["name"].casefold())


def get_hall_scheme(actor: CurrentUser, hall_id: int, db_path=None) -> dict:
    """Схема зала для GUI:
        {"hall": {...}, "rows": [{"row_number": 1, "seats": [{"id", "seat_number", "seat_type"}, ...]}, ...]}
    Занятость мест на конкретный сеанс добавится в модуле билетов.
    """
    actor.require(Permission.VIEW_HALL_SCHEME)
    with connection(db_path) as conn:
        hall = _get_or_fail(conn, hall_id)
        seats = crud.list_seats_by_hall(conn, hall_id)
    rows: dict[int, list] = {}
    for seat in seats:
        rows.setdefault(seat["row_number"], []).append(
            {"id": seat["id"], "seat_number": seat["seat_number"], "seat_type": seat["seat_type"]})
    return {"hall": dict(hall),
            "rows": [{"row_number": r, "seats": rows[r]} for r in sorted(rows)]}


# ------------------------------------------------------------------ изменение

def create_hall(actor: CurrentUser, name, rows, seats_per_row, vip_rows=(), db_path=None) -> int:
    """Создаёт зал и сразу генерирует места. Вместимость = ряды × места в ряду.

    Зал и места создаются в одной транзакции: либо всё, либо ничего.
    """
    actor.require(Permission.MANAGE_HALLS)
    name = clean_text(name, "Название зала", 50)
    rows, seats_per_row, vip = _validate_layout(rows, seats_per_row, vip_rows)
    try:
        with transaction(db_path) as conn:
            _ensure_name_free(conn, name)
            hall_id = crud.create_hall(conn, name, rows * seats_per_row)
            crud.create_seats_bulk(conn, hall_id, _build_seats(rows, seats_per_row, vip))
            return hall_id
    except DBError as exc:
        raise db_error_to_validation(exc, _DUPLICATE_MSG) from exc


def rename_hall(actor: CurrentUser, hall_id: int, new_name, db_path=None) -> None:
    actor.require(Permission.MANAGE_HALLS)
    new_name = clean_text(new_name, "Название зала", 50)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, hall_id)
            _ensure_name_free(conn, new_name, exclude_id=hall_id)
            crud.update_hall(conn, hall_id, name=new_name)
    except DBError as exc:
        raise db_error_to_validation(exc, _DUPLICATE_MSG) from exc


def reconfigure_hall(actor: CurrentUser, hall_id: int, rows, seats_per_row, vip_rows=(),
                     db_path=None) -> None:
    """Пересоздаёт схему мест зала. Только если в зале ещё нет сеансов:
    иначе пропали бы места, на которые продаются или уже проданы билеты."""
    actor.require(Permission.MANAGE_HALLS)
    rows, seats_per_row, vip = _validate_layout(rows, seats_per_row, vip_rows)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, hall_id)
            _ensure_no_sessions(conn, hall_id, "изменить схему зала")
            crud.delete_seats_by_hall(conn, hall_id)
            crud.create_seats_bulk(conn, hall_id, _build_seats(rows, seats_per_row, vip))
            crud.update_hall(conn, hall_id, capacity=rows * seats_per_row)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc


def set_seat_type(actor: CurrentUser, seat_id: int, seat_type: str, db_path=None) -> None:
    """Меняет тип одного места (обычное/VIP), если на него ещё не оформляли билеты."""
    actor.require(Permission.MANAGE_HALLS)
    _validate_seat_type(seat_type)
    try:
        with transaction(db_path) as conn:
            if crud.get_seat(conn, seat_id) is None:
                raise ValidationError("Место не найдено.")
            if crud.count_tickets_for_seats(conn, [seat_id]):
                raise ValidationError("Нельзя изменить тип места: на него уже оформлялись билеты.")
            crud.update_seat(conn, seat_id, seat_type=seat_type)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc


def set_row_type(actor: CurrentUser, hall_id: int, row_number, seat_type: str, db_path=None) -> None:
    """Меняет тип всех мест ряда (например, сделать 5-й ряд VIP)."""
    actor.require(Permission.MANAGE_HALLS)
    _validate_seat_type(seat_type)
    row_number = parse_int(row_number, "Ряд", 1, MAX_ROWS)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, hall_id)
            row_seats = [s for s in crud.list_seats_by_hall(conn, hall_id)
                         if s["row_number"] == row_number]
            if not row_seats:
                raise ValidationError("В зале нет такого ряда.")
            if crud.count_tickets_for_seats(conn, [s["id"] for s in row_seats]):
                raise ValidationError("Нельзя изменить тип ряда: на его места уже оформлялись билеты.")
            for seat in row_seats:
                crud.update_seat(conn, seat["id"], seat_type=seat_type)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc


def delete_hall(actor: CurrentUser, hall_id: int, db_path=None) -> None:
    """Удаляет зал вместе с местами, если в нём нет сеансов."""
    actor.require(Permission.MANAGE_HALLS)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, hall_id)
            _ensure_no_sessions(conn, hall_id, "удалить зал")
            crud.delete_hall(conn, hall_id)  # места удалятся каскадом (ON DELETE CASCADE)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc
