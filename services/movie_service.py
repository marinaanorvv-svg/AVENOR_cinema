"""Справочник фильмов (афиша)."""
import hashlib
import os
import re
import shutil
from pathlib import Path

from database import crud
from database.connection import connection, transaction
from database.errors import DBError

from .errors import ValidationError
from .permissions import CurrentUser, Permission
from .validators import clean_text, db_error_to_validation, parse_int

AGE_RATINGS = ("0+", "6+", "12+", "16+", "18+")
POSTER_EXTENSIONS = (".png", ".gif", ".jpg", ".jpeg")
MAX_DURATION_MIN = 600
PROJECT_ROOT = Path(__file__).resolve().parent.parent
POSTERS_DIR = PROJECT_ROOT / "posters"      # сюда копируются выбранные постеры, в БД хранится «posters/имя.png»
MAX_POSTER_BYTES = 10 * 1024 * 1024


def poster_file(path) -> Path | None:
    """Полный путь к файлу постера по значению из БД (относительные пути — от папки программы)."""
    if not path:
        return None
    candidate = Path(path)
    return candidate if candidate.is_absolute() else POSTERS_DIR.parent / candidate


def _import_poster(path: str) -> str:
    """Копирует выбранный файл в папку posters/ и возвращает путь для БД.

    Так постер не пропадёт, если исходный файл переместят или удалят, и проект
    можно переносить на другой компьютер вместе с папкой posters/.
    """
    stored = path.replace("\\", "/")
    if stored.startswith(f"{POSTERS_DIR.name}/"):
        return stored                         # уже в папке программы (при правке фильма без смены постера)
    source = Path(path)
    if not source.is_file():
        raise ValidationError("Файл постера не найден. Выберите его заново.")
    if source.stat().st_size > MAX_POSTER_BYTES:
        raise ValidationError("Файл постера больше 10 МБ.")
    digest = hashlib.sha1(source.read_bytes()).hexdigest()[:8]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", source.stem).strip("_")[:30] or "poster"
    name = f"{stem}_{digest}{source.suffix.lower()}"
    target = POSTERS_DIR / name
    if not target.exists():
        try:
            POSTERS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            for size in ("small", "large"):   # готовые PNG под карточки (для компьютеров без Pillow)
                variant = source.with_name(f"{source.stem}@{size}.png")
                if variant.is_file():
                    shutil.copy2(variant, target.with_name(f"{target.stem}@{size}.png"))
        except OSError as exc:
            raise ValidationError(f"Не удалось сохранить постер: {exc.strerror or exc}.") from exc
    return f"{POSTERS_DIR.name}/{name}"


_EDITABLE_FIELDS = {"title", "genre_id", "duration", "age_rating", "description", "poster_path"}


def _validate_fields(conn, fields: dict) -> dict:
    """Проверяет и нормализует только переданные поля (годится и для создания, и для правки)."""
    unknown = set(fields) - _EDITABLE_FIELDS
    if unknown:
        raise ValidationError(f"Неизвестные поля: {', '.join(sorted(unknown))}.")

    clean = {}
    if "title" in fields:
        clean["title"] = clean_text(fields["title"], "Название", 200)
    if "genre_id" in fields:
        genre_id = parse_int(fields["genre_id"], "Жанр", 1)
        if crud.get_genre(conn, genre_id) is None:
            raise ValidationError("Выбранный жанр не существует.")
        clean["genre_id"] = genre_id
    if "duration" in fields:
        clean["duration"] = parse_int(fields["duration"], "Длительность (мин)", 1, MAX_DURATION_MIN)
    if "age_rating" in fields:
        rating = (fields["age_rating"] or "").strip() if isinstance(fields["age_rating"], str) else ""
        if rating not in AGE_RATINGS:
            raise ValidationError(f"Возрастной рейтинг: допустимо {', '.join(AGE_RATINGS)}.")
        clean["age_rating"] = rating
    if "description" in fields:
        clean["description"] = clean_text(fields["description"], "Описание", 2000,
                                          required=False, collapse=False)
    if "poster_path" in fields:
        path = clean_text(fields["poster_path"], "Постер", 500, required=False)
        if path and os.path.splitext(path)[1].lower() not in POSTER_EXTENSIONS:
            raise ValidationError("Постер: допустимы файлы PNG, GIF, JPG.")
        clean["poster_path"] = _import_poster(path) if path else None
    return clean


def _get_or_fail(conn, movie_id):
    movie = crud.get_movie(conn, movie_id)
    if movie is None:
        raise ValidationError("Фильм не найден.")
    return movie


def list_movies(actor: CurrentUser, genre_id=None, search=None, db_path=None) -> list[dict]:
    """Афиша: все фильмы с названием жанра, с необязательным фильтром.

    Поиск делаем в Python через casefold: SQLite LIKE не умеет регистронезависимый
    поиск по кириллице.
    """
    actor.require(Permission.VIEW_SCHEDULE)
    with connection(db_path) as conn:
        movies = [dict(m) for m in crud.list_movies_with_genre(conn)]
    if genre_id is not None:
        movies = [m for m in movies if m["genre_id"] == genre_id]
    if search and search.strip():
        needle = search.strip().casefold()
        movies = [m for m in movies if needle in m["title"].casefold()]
    return sorted(movies, key=lambda m: m["title"].casefold())


def get_movie(actor: CurrentUser, movie_id: int, db_path=None) -> dict:
    actor.require(Permission.VIEW_SCHEDULE)
    with connection(db_path) as conn:
        movie = crud.get_movie_with_genre(conn, movie_id)
    if movie is None:
        raise ValidationError("Фильм не найден.")
    return dict(movie)


def create_movie(actor: CurrentUser, title, genre_id, duration, age_rating="0+",
                 description=None, poster_path=None, db_path=None) -> int:
    actor.require(Permission.MANAGE_MOVIES)
    try:
        with transaction(db_path) as conn:
            clean = _validate_fields(conn, {
                "title": title, "genre_id": genre_id, "duration": duration,
                "age_rating": age_rating, "description": description,
                "poster_path": poster_path})
            return crud.create_movie(conn, **clean)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc


def update_movie(actor: CurrentUser, movie_id: int, db_path=None, **fields) -> None:
    """Частичное обновление: update_movie(actor, 5, title="Новое", duration=130)."""
    actor.require(Permission.MANAGE_MOVIES)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, movie_id)
            clean = _validate_fields(conn, fields)
            crud.update_movie(conn, movie_id, **clean)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc


def delete_movie(actor: CurrentUser, movie_id: int, db_path=None) -> None:
    """Удаляет фильм, если на него нет сеансов."""
    actor.require(Permission.MANAGE_MOVIES)
    try:
        with transaction(db_path) as conn:
            _get_or_fail(conn, movie_id)
            used = crud.count_sessions_by_movie(conn, movie_id)
            if used:
                raise ValidationError(
                    f"Нельзя удалить фильм: на него назначены сеансы ({used}). "
                    "Сначала удалите сеансы.")
            crud.delete_movie(conn, movie_id)
    except DBError as exc:
        raise db_error_to_validation(exc) from exc
