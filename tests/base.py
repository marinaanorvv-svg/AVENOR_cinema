"""Общая основа для тестов сервисов: временная БД, admin/cashier/viewer, быстрые помощники."""
import tempfile
import unittest
from pathlib import Path

from database import crud
from database.connection import transaction
from services import auth_service as auth
from services import genre_service as genres
from services import hall_service as halls
from services import movie_service as movies
from services.permissions import Role


class CatalogTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "test.db"
        auth.ensure_default_admin(self.db)
        self.admin = auth.login("admin", "admin123", self.db)
        for name, role in (("cash", Role.CASHIER), ("view", Role.VIEWER)):
            auth.create_user_account(self.admin, name, "secret1", role, name, db_path=self.db)
        self.cashier = auth.login("cash", "secret1", self.db)
        self.viewer = auth.login("view", "secret1", self.db)

    def tearDown(self):
        self._tmp.cleanup()

    # быстрые обёртки
    def genre(self, name="Драма"):
        return genres.create_genre(self.admin, name, self.db)

    def movie(self, title="Фильм", genre_id=None, **kw):
        genre_id = genre_id or self.genre(f"Жанр для {title}")
        return movies.create_movie(self.admin, title, genre_id, kw.pop("duration", 120),
                                   db_path=self.db, **kw)

    def hall(self, name="Зал 1", rows=5, per_row=10, vip=""):
        return halls.create_hall(self.admin, name, rows, per_row, vip, self.db)

    def add_session(self, movie_id, hall_id, time="18:00"):
        with transaction(self.db) as conn:
            return crud.create_session(conn, movie_id, hall_id, "2026-11-01", time, 300)
