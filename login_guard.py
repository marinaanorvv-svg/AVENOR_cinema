"""Ограничение частоты попыток входа (без tkinter).

После MAX_ATTEMPTS неудач подряд вход блокируется на LOCK_SECONDS секунд —
простая защита от подбора пароля на экране входа.
"""
from datetime import timedelta

from services import clock


class LoginAttemptLimiter:
    def __init__(self, max_attempts=5, lock_seconds=30, now=None):
        self.max_attempts = max_attempts
        self.lock_seconds = lock_seconds
        self._now = now or clock.now
        self._failures = 0
        self._locked_until = None

    def seconds_left(self) -> int:
        """Сколько секунд вход ещё заблокирован (0 — можно пробовать)."""
        if self._locked_until is None:
            return 0
        left = (self._locked_until - self._now()).total_seconds()
        if left <= 0:
            self._locked_until, self._failures = None, 0
            return 0
        return int(left) + (1 if left % 1 else 0)

    def register_failure(self) -> bool:
        """Учитывает неудачную попытку. True — после неё вход заблокирован."""
        self._failures += 1
        if self._failures >= self.max_attempts:
            self._locked_until = self._now() + timedelta(seconds=self.lock_seconds)
            return True
        return False

    def register_success(self) -> None:
        self._failures, self._locked_until = 0, None
