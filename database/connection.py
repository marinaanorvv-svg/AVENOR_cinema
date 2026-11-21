"""Подключение к SQLite и управление транзакциями."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Файл БД лежит в корне проекта рядом с main.py
DB_PATH = Path(__file__).resolve().parent.parent / "cinema.db"


def get_connection(db_path=None) -> sqlite3.Connection:
    """Открывает соединение с БД.

    - row_factory=Row: к полям строки можно обращаться по имени (row["title"]);
    - foreign_keys=ON: в SQLite внешние ключи по умолчанию ВЫКЛЮЧЕНЫ,
      их нужно включать для каждого соединения отдельно;
    - timeout: если БД занята другой записью, ждём до 10 секунд, а не падаем сразу.
    """
    conn = sqlite3.connect(str(db_path or DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(db_path=None):
    """Контекстный менеджер: одна транзакция на блок with.

    with transaction() as conn:
        ...несколько операций...

    Успешный выход — commit, любое исключение — rollback (изменения откатываются).
    BEGIN IMMEDIATE сразу берёт блокировку на запись: два кассира не смогут
    одновременно пройти проверку «место свободно» и оба продать билет.
    """
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def connection(db_path=None):
    """Соединение для операций ЧТЕНИЯ: открыли, прочитали, закрыли.

    Для записи используйте transaction().
    """
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
