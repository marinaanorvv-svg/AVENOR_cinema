"""Собственные исключения слоя БД.

Сервисы и GUI ловят только их, а не sqlite3.Error, и показывают
пользователю понятное сообщение (str(exc)).
"""


class DBError(Exception):
    """Базовая ошибка слоя БД."""


class NotFoundError(DBError):
    """Запись с указанным id не найдена."""


class ConstraintError(DBError):
    """Нарушено ограничение целостности (UNIQUE, FOREIGN KEY, CHECK, NOT NULL).

    kind  — тип нарушения: 'unique' | 'foreign_key' | 'not_null' | 'check' | 'other'
    detail — исходный текст ошибки SQLite (удобно для отладки и логов)
    """

    def __init__(self, message: str, kind: str = "other", detail: str = ""):
        super().__init__(message)
        self.kind = kind
        self.detail = detail
