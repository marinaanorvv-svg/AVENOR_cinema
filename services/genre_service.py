"""Справочник жанров."""
from database import crud
from database.connection import connection, transaction
from database.errors import DBError

from .errors import ValidationError
from .permissions import CurrentUser, Permission
from .validators import clean_text, db_error_to_validation

_DUPLICATE_MSG = "Такой жанр уже существует."


def _ensure_name_free(conn, name, exclude_id=None):
    """Проверка уникальности без учёта регистра («драма» == «Драма»).

    UNIQUE в SQLite различает регистр, поэтому сравниваем в Python через casefold.
    """
    for genre in crud.list_genres(conn):
        if genre["id"] != exclude_id and genre["name"].casefold() == name.casefold():
            raise ValidationError(_DUPLICATE_MSG)


def _get_or_fail(conn, genre_id):
    genre = crud.get_genre(conn, genre_id)
    if genre is None:
        raise ValidationError("Жанр не найден.")
    return genre


def list_genres(actor: CurrentUser, db_path=None) -> list[dict]:
    actor.require(Permission.VIEW_SCHEDULE)
    with connection(db_path) as conn:
        genres = [dict(g) for g in crud.list_genres(conn)]
    return sorted(genres, key=lambda g: g["name"].casefold())


def create_genre(actor: CurrentUser, name, db_path=None) -> int:
    actor.require(Permission.MANAGE_GENRES)
    name = clean_text(name, "Название жанра", 50)
    try:
        with transaction(db_path) as conn:
            _ensure_name_free(conn, name)
            return crud.create_genre(conn, name)
    except DBError as exc:
        raise db_error_to_validation(exc, _DUPLICATE_MSG) from exc


def rename_genre(actor: CurrentUser, genre_id: int, new_name, db_path=None) -> None:
    actor.require(Permission.MANAGE_GENRES)
    new_name = clean_text(new_name, "Название жанра", 50)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, genre_id)
            _ensure_name_free(conn, new_name, exclude_id=genre_id)
            crud.update_genre(conn, genre_id, name=new_name)
    except DBError as exc:
        raise db_error_to_validation(exc, _DUPLICATE_MSG) from exc


def delete_genre(actor: CurrentUser, genre_id: int, db_path=None) -> None:
    """Удаляет жанр, только если ни один фильм его не использует."""
    actor.require(Permission.MANAGE_GENRES)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, genre_id)
            used = crud.count_movies_by_genre(conn, genre_id)
            if used:
                raise ValidationError(
                    f"Нельзя удалить жанр: он указан у фильмов ({used}). "
                    "Сначала измените жанр у этих фильмов.")
            crud.delete_genre(conn, genre_id)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc
