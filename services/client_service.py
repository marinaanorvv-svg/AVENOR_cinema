"""Клиенты: выбор существующего или создание нового при продаже билета."""
import re

from database import crud
from database.connection import connection

from .errors import ValidationError
from .permissions import CurrentUser, Permission
from .validators import clean_text, normalize_email, normalize_phone, parse_int


def validate_client_input(client):
    """Проверяет данные клиента ДО открытия транзакции (чтобы не держать блокировку БД).

    client — id существующего клиента (int/str) или словарь
    {"full_name": ..., "phone": ..., "email": ...}; телефон и email необязательны.
    """
    if client is None or client == "":
        raise ValidationError("Укажите клиента.")
    if isinstance(client, dict):
        return {"full_name": clean_text(client.get("full_name"), "ФИО клиента", 100),
                "phone": normalize_phone(client.get("phone")),
                "email": normalize_email(client.get("email"))}
    return parse_int(client, "Клиент", 1)


def resolve_client(conn, client) -> int:
    """Возвращает id клиента внутри уже открытой транзакции.

    Для словаря сначала ищем существующего по телефону, затем по email — так один
    человек не дублируется, и не нарушается уникальность этих полей. Данные найденного
    клиента не перезаписываются.
    """
    if isinstance(client, int):
        if crud.get_client(conn, client) is None:
            raise ValidationError("Клиент не найден.")
        return client
    existing = None
    if client["phone"]:
        existing = crud.get_client_by_phone(conn, client["phone"])
    if existing is None and client["email"]:
        existing = crud.get_client_by_email(conn, client["email"])
    if existing is not None:
        return existing["id"]
    return crud.create_client(conn, client["full_name"], client["phone"], client["email"])


def search_clients(actor: CurrentUser, query, limit=50, db_path=None) -> list[dict]:
    """Поиск клиентов по ФИО, email или части телефона (для выбора на кассе)."""
    actor.require(Permission.SELL_TICKET)
    text = (query or "").strip().casefold()
    digits = re.sub(r"\D", "", text)
    with connection(db_path) as conn:
        clients = [dict(c) for c in crud.list_clients(conn)]
    if text:
        def matches(c):
            return (text in c["full_name"].casefold()
                    or text in (c["email"] or "").casefold()
                    or (len(digits) >= 3 and digits in re.sub(r"\D", "", c["phone"] or "")))
        clients = [c for c in clients if matches(c)]
    return sorted(clients, key=lambda c: c["full_name"].casefold())[:limit]
