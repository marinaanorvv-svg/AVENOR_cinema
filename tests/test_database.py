"""Проверка слоя БД. Запуск из корня проекта:  python -m unittest tests.test_database -v"""
import unittest

from database import crud
from database.connection import get_connection
from database.errors import ConstraintError, NotFoundError
from database.schema import create_schema


class DatabaseLayerTests(unittest.TestCase):
    def setUp(self):
        # БД в памяти: каждый тест начинается с чистого листа
        self.conn = get_connection(":memory:")
        create_schema(self.conn)
        # минимальный набор данных для билетов
        g = crud.create_genre(self.conn, "Драма")
        self.movie = crud.create_movie(self.conn, "Фильм", g, 120, "12+")
        self.hall = crud.create_hall(self.conn, "Зал 1", 2)
        self.seat1 = crud.create_seat(self.conn, self.hall, 1, 1)
        self.seat2 = crud.create_seat(self.conn, self.hall, 1, 2, "vip")
        self.session = crud.create_session(self.conn, self.movie, self.hall,
                                           "2026-10-20", "18:00", 350)
        self.client = crud.create_client(self.conn, "Иван Петров", "+79990000000")

    def tearDown(self):
        self.conn.close()

    def test_all_tables_created(self):
        names = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("users", "genres", "movies", "halls", "seats",
                  "sessions", "clients", "tickets"):
            self.assertIn(t, names)

    def test_crud_roundtrip(self):
        self.assertEqual(crud.get_movie(self.conn, self.movie)["title"], "Фильм")
        crud.update_movie(self.conn, self.movie, title="Новое название",
                          poster_path="posters/1.png")
        self.assertEqual(crud.get_movie(self.conn, self.movie)["poster_path"], "posters/1.png")
        self.assertEqual(crud.get_movie(self.conn, self.movie)["title"], "Новое название")

    def test_update_missing_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            crud.update_genre(self.conn, 9999, name="X")

    def test_unique_username(self):
        crud.create_user(self.conn, "admin", "hash", "admin", "Админ")
        with self.assertRaises(ConstraintError) as ctx:
            crud.create_user(self.conn, "admin", "hash", "admin", "Другой")
        self.assertEqual(ctx.exception.kind, "unique")

    def test_invalid_role_rejected(self):
        with self.assertRaises(ConstraintError) as ctx:
            crud.create_user(self.conn, "hacker", "hash", "superuser", "X")
        self.assertEqual(ctx.exception.kind, "check")

    def test_foreign_keys_enforced(self):
        with self.assertRaises(ConstraintError) as ctx:
            crud.create_movie(self.conn, "Без жанра", 9999, 90)
        self.assertEqual(ctx.exception.kind, "foreign_key")

    def test_cannot_delete_genre_in_use(self):
        genre_id = crud.get_movie(self.conn, self.movie)["genre_id"]
        with self.assertRaises(ConstraintError):
            crud.delete_genre(self.conn, genre_id)

    def test_double_sale_blocked_but_resale_after_return_allowed(self):
        t = crud.create_ticket(self.conn, self.session, self.seat1, self.client)
        with self.assertRaises(ConstraintError) as ctx:
            crud.create_ticket(self.conn, self.session, self.seat1, self.client)
        self.assertEqual(ctx.exception.kind, "unique")
        crud.update_ticket(self.conn, t, status="returned")
        crud.create_ticket(self.conn, self.session, self.seat1, self.client)  # ok

    def test_seat_must_belong_to_session_hall(self):
        other_hall = crud.create_hall(self.conn, "Зал 2", 1)
        foreign_seat = crud.create_seat(self.conn, other_hall, 1, 1)
        with self.assertRaises(ConstraintError):
            crud.create_ticket(self.conn, self.session, foreign_seat, self.client)

    def test_deleting_hall_removes_its_seats(self):
        empty_hall = crud.create_hall(self.conn, "Пустой", 1)
        crud.create_seat(self.conn, empty_hall, 1, 1)
        crud.delete_hall(self.conn, empty_hall)
        self.assertEqual(len(crud.list_seats_by_hall(self.conn, empty_hall)), 0)


class MigrationTests(unittest.TestCase):
    def test_old_database_gets_new_columns(self):
        """БД, созданная ранней версией схемы (без poster_path и returned_at), обновляется на месте."""
        conn = get_connection(":memory:")
        conn.executescript("""
            CREATE TABLE movies (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                genre_id INTEGER NOT NULL, duration INTEGER NOT NULL,
                age_rating TEXT NOT NULL DEFAULT '0+', description TEXT);
            CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL,
                seat_id INTEGER NOT NULL, client_id INTEGER NOT NULL,
                purchase_date TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                status TEXT NOT NULL DEFAULT 'sold');
        """)
        create_schema(conn)
        create_schema(conn)   # повторный вызов безопасен
        cols = lambda table: {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        self.assertIn("poster_path", cols("movies"))
        self.assertIn("returned_at", cols("tickets"))
        conn.close()


if __name__ == "__main__":
    unittest.main()
