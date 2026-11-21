"""Единый источник текущего времени для сервисов.

Сервисы вызывают clock.now(), а не datetime.now() напрямую: так в тестах время
подменяется в одном месте (patch("services.clock.now")), без правки кода.
"""
from datetime import datetime


def now() -> datetime:
    return datetime.now()
