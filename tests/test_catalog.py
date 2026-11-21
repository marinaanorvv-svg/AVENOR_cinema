"""Проверка справочников: жанры, фильмы, залы. Запуск:  python -m unittest tests.test_catalog -v"""
import unittest

from database import crud
from database.connection import get_connection, transaction
from services import genre_service as genres
from services import hall_service as halls
from services import movie_service as movies
from services.errors import PermissionDenied, ValidationError
from tests.base import CatalogTestCase


class GenreTests(CatalogTestCase):
    def test_create_normalizes_and_lists_sorted(self):
        self.genre("  комедия   ")
        self.genre("Ужасы")
        names = [g["name"] for g in genres.list_genres(self.viewer, self.db)]
        self.assertEqual(names, ["комедия", "Ужасы"])  # без учёта регистра, пробелы убраны

    def test_validation(self):
        for bad in ("", "   ", None, "x" * 51):
            with self.assertRaises(ValidationError):
                genres.create_genre(self.admin, bad, self.db)

    def test_duplicate_case_insensitive(self):
        self.genre("Драма")
        with self.assertRaises(ValidationError):
            genres.create_genre(self.admin, "драма", self.db)

    def test_rename_and_conflict(self):
        a, _ = self.genre("А-жанр"), self.genre("Б-жанр")
        genres.rename_genre(self.admin, a, "А-жанр", self.db)          # то же имя — не конфликт
        with self.assertRaises(ValidationError):
            genres.rename_genre(self.admin, a, "б-ЖАНР", self.db)

    def test_delete_unused_and_used(self):
        free, used = self.genre("Свободный"), self.genre("Занятый")
        movies.create_movie(self.admin, "Ф", used, 100, db_path=self.db)
        genres.delete_genre(self.admin, free, self.db)
        with self.assertRaises(ValidationError) as ctx:
            genres.delete_genre(self.admin, used, self.db)
        self.assertIn("фильмов", str(ctx.exception))

    def test_permissions(self):
        genres.list_genres(self.cashier, self.db)  # читать можно
        for actor in (self.cashier, self.viewer):
            with self.assertRaises(PermissionDenied):
                genres.create_genre(actor, "Новый", self.db)


class MovieTests(CatalogTestCase):
    def test_create_and_list_with_genre_name(self):
        gid = self.genre("Фантастика")
        mid = movies.create_movie(self.admin, " Дюна ", gid, "155", "12+", "Описание",
                                  "posters/dune.PNG", self.db)
        item = movies.get_movie(self.viewer, mid, self.db)
        self.assertEqual(item["title"], "Дюна")
        self.assertEqual(item["duration"], 155)
        self.assertEqual(item["genre_name"], "Фантастика")

    def test_invalid_duration(self):
        gid = self.genre()
        for bad in ("abc", 0, 601, "1.5", True, "", None):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                movies.create_movie(self.admin, "Ф", gid, bad, db_path=self.db)

    def test_invalid_rating_genre_poster_title(self):
        gid = self.genre()
        cases = [dict(title="Ф", genre_id=gid, duration=90, age_rating="21+"),
                 dict(title="Ф", genre_id=9999, duration=90),
                 dict(title="Ф", genre_id=gid, duration=90, poster_path="x.exe"),
                 dict(title="  ", genre_id=gid, duration=90)]
        for kwargs in cases:
            with self.assertRaises(ValidationError, msg=repr(kwargs)):
                movies.create_movie(self.admin, db_path=self.db, **kwargs)

    def test_poster_is_copied_into_program_folder(self):
        import os
        from pathlib import Path
        from unittest.mock import patch
        source = Path(self._tmp.name) / "Мой постер (1).PNG"
        source.write_bytes(b"png-bytes")
        folder = Path(self._tmp.name) / "posters"
        with patch("services.movie_service.POSTERS_DIR", folder):
            mid = self.movie("С постером", poster_path=str(source))
            stored = movies.get_movie(self.admin, mid, self.db)["poster_path"]
            self.assertRegex(stored, r"^posters/[A-Za-z0-9_-]+_[0-9a-f]{8}\.png$")   # безопасное имя + хеш содержимого
            copied = movies.poster_file(stored)
            self.assertEqual(copied.read_bytes(), b"png-bytes")
            source.unlink()                                                           # исходный файл удалён — постер на месте
            self.assertTrue(copied.exists())
            movies.update_movie(self.admin, mid, self.db, poster_path=stored, title="Новое имя")   # без смены — не трогаем
            self.assertEqual(movies.get_movie(self.admin, mid, self.db)["poster_path"], stored)
            self.assertEqual(len(list(folder.iterdir())), 1)
            with self.assertRaises(ValidationError):
                movies.update_movie(self.admin, mid, self.db, poster_path=str(Path(self._tmp.name) / "нет.png"))
            big = Path(self._tmp.name) / "big.png"
            big.write_bytes(b"0" * 10)
            with patch("services.movie_service.MAX_POSTER_BYTES", 5), self.assertRaises(ValidationError):
                movies.update_movie(self.admin, mid, self.db, poster_path=str(big))

    def test_partial_update(self):
        mid = self.movie("Старое")
        movies.update_movie(self.admin, mid, self.db, title="Новое", duration="99")
        item = movies.get_movie(self.admin, mid, self.db)
        self.assertEqual((item["title"], item["duration"]), ("Новое", 99))
        with self.assertRaises(ValidationError):
            movies.update_movie(self.admin, mid, self.db, id=5)         # неизвестное поле
        with self.assertRaises(ValidationError):
            movies.update_movie(self.admin, 9999, self.db, title="X")   # нет такого фильма

    def test_search_is_case_insensitive_for_cyrillic(self):
        self.movie("Властелин колец")
        self.movie("Дюна")
        found = movies.list_movies(self.viewer, search="ВЛАСТЕЛИН", db_path=self.db)
        self.assertEqual([m["title"] for m in found], ["Властелин колец"])

    def test_filter_by_genre(self):
        g1 = self.genre("Один")
        self.movie("А", genre_id=g1)
        self.movie("Б")
        self.assertEqual(len(movies.list_movies(self.viewer, genre_id=g1, db_path=self.db)), 1)

    def test_delete_blocked_by_sessions(self):
        mid, hid = self.movie("С сеансом"), self.hall()
        self.add_session(mid, hid)
        with self.assertRaises(ValidationError) as ctx:
            movies.delete_movie(self.admin, mid, self.db)
        self.assertIn("сеансы", str(ctx.exception))
        free = self.movie("Без сеансов")
        movies.delete_movie(self.admin, free, self.db)

    def test_permissions(self):
        gid = self.genre()
        with self.assertRaises(PermissionDenied):
            movies.create_movie(self.cashier, "Ф", gid, 90, db_path=self.db)
        with self.assertRaises(PermissionDenied):
            movies.delete_movie(self.viewer, 1, self.db)
        movies.list_movies(self.viewer, db_path=self.db)  # афиша доступна пользователю


class HallTests(CatalogTestCase):
    def test_create_generates_seats_and_vip_rows(self):
        hid = self.hall(rows=5, per_row=10, vip="4, 5")
        scheme = halls.get_hall_scheme(self.cashier, hid, self.db)
        self.assertEqual(scheme["hall"]["capacity"], 50)
        self.assertEqual(len(scheme["rows"]), 5)
        for row in scheme["rows"]:
            self.assertEqual(len(row["seats"]), 10)
            expected = "vip" if row["row_number"] in (4, 5) else "regular"
            self.assertTrue(all(s["seat_type"] == expected for s in row["seats"]))

    def test_layout_validation(self):
        bad = [dict(rows=0, per_row=10), dict(rows=31, per_row=10), dict(rows=5, per_row=0),
               dict(rows=5, per_row=41), dict(rows="x", per_row=10),
               dict(rows=5, per_row=10, vip="6"), dict(rows=5, per_row=10, vip="a")]
        for i, kw in enumerate(bad):
            with self.assertRaises(ValidationError, msg=repr(kw)):
                halls.create_hall(self.admin, f"Зал {i}", kw["rows"], kw["per_row"],
                                  kw.get("vip", ""), self.db)

    def test_failed_creation_leaves_nothing(self):
        with self.assertRaises(ValidationError):
            halls.create_hall(self.admin, "Плохой", 5, 10, "9", self.db)
        self.assertEqual(halls.list_halls(self.admin, self.db), [])

    def test_duplicate_name_case_insensitive(self):
        self.hall("Большой зал")
        with self.assertRaises(ValidationError):
            halls.create_hall(self.admin, "большой ЗАЛ", 2, 2, db_path=self.db)

    def test_rename(self):
        hid = self.hall("Старый")
        halls.rename_hall(self.admin, hid, "Новый", self.db)
        self.assertEqual(halls.list_halls(self.viewer, self.db)[0]["name"], "Новый")

    def test_reconfigure_without_and_with_sessions(self):
        hid = self.hall(rows=2, per_row=2)
        halls.reconfigure_hall(self.admin, hid, 3, 4, "1", self.db)
        scheme = halls.get_hall_scheme(self.admin, hid, self.db)
        self.assertEqual(scheme["hall"]["capacity"], 12)
        self.assertEqual(sum(len(r["seats"]) for r in scheme["rows"]), 12)
        self.add_session(self.movie(), hid)
        with self.assertRaises(ValidationError):
            halls.reconfigure_hall(self.admin, hid, 1, 1, "", self.db)

    def test_delete_hall(self):
        free, busy = self.hall("Свободный", 1, 2), self.hall("Занятый", 1, 2)
        self.add_session(self.movie(), busy)
        halls.delete_hall(self.admin, free, self.db)
        with self.assertRaises(ValidationError):
            halls.delete_hall(self.admin, busy, self.db)
        with get_connection(self.db) as conn:   # места удалённого зала исчезли каскадом
            self.assertEqual(len(crud.list_seats_by_hall(conn, free)), 0)

    def test_set_seat_and_row_type(self):
        hid = self.hall(rows=2, per_row=3)
        scheme = halls.get_hall_scheme(self.admin, hid, self.db)
        seat_id = scheme["rows"][0]["seats"][0]["id"]
        halls.set_seat_type(self.admin, seat_id, "vip", self.db)
        halls.set_row_type(self.admin, hid, 2, "vip", self.db)
        scheme = halls.get_hall_scheme(self.admin, hid, self.db)
        self.assertEqual(scheme["rows"][0]["seats"][0]["seat_type"], "vip")
        self.assertEqual(scheme["rows"][0]["seats"][1]["seat_type"], "regular")
        self.assertTrue(all(s["seat_type"] == "vip" for s in scheme["rows"][1]["seats"]))
        with self.assertRaises(ValidationError):
            halls.set_seat_type(self.admin, seat_id, "gold", self.db)
        with self.assertRaises(ValidationError):
            halls.set_row_type(self.admin, hid, 9, "vip", self.db)

    def test_seat_type_locked_after_ticket(self):
        hid = self.hall(rows=1, per_row=2)
        sid = self.add_session(self.movie(), hid)
        seat_id = halls.get_hall_scheme(self.admin, hid, self.db)["rows"][0]["seats"][0]["id"]
        with transaction(self.db) as conn:
            client = crud.create_client(conn, "Клиент")
            crud.create_ticket(conn, sid, seat_id, client)
        with self.assertRaises(ValidationError):
            halls.set_seat_type(self.admin, seat_id, "vip", self.db)
        with self.assertRaises(ValidationError):
            halls.set_row_type(self.admin, hid, 1, "vip", self.db)

    def test_permissions(self):
        hid = self.hall()
        with self.assertRaises(PermissionDenied):
            halls.create_hall(self.cashier, "Зал X", 2, 2, db_path=self.db)
        with self.assertRaises(PermissionDenied):
            halls.get_hall_scheme(self.viewer, hid, self.db)   # схема зала — не для пользователя
        halls.list_halls(self.viewer, self.db)                  # список залов — можно
        halls.get_hall_scheme(self.cashier, hid, self.db)       # кассиру схема нужна


if __name__ == "__main__":
    unittest.main()
