"""Проверка демо-данных и предложения загрузить их при запуске. Запуск:  python -m unittest tests.test_seed -v"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main as app_main
import seed_demo
from database import crud
from database.connection import connection
from services import auth_service as auth
from services import session_service, ticket_service


class FakeMessagebox:
    def __init__(self, answer=True):
        self.answer, self.calls = answer, []

    def askyesno(self, title, message, **kwargs):
        self.calls.append(("ask", message))
        return self.answer

    def showinfo(self, title, message, **kwargs):
        self.calls.append(("info", message))

    def showwarning(self, title, message, **kwargs):
        self.calls.append(("warning", message))

    def showerror(self, title, message, **kwargs):
        self.calls.append(("error", message))


class SeedTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch("database.connection.DB_PATH", Path(self._tmp.name) / "demo.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        posters = patch("services.movie_service.POSTERS_DIR", Path(self._tmp.name) / "posters")   # постеры — во временную папку
        posters.start()
        self.addCleanup(posters.stop)
        self.addCleanup(self._tmp.cleanup)

    def counts(self):
        with connection() as conn:
            return (len(crud.list_movies(conn)), len(crud.list_halls(conn)), len(crud.list_sessions(conn)),
                    len(crud.list_tickets(conn)))

    def test_seed_fills_database_and_refuses_to_repeat(self):
        with patch("builtins.print"):
            self.assertEqual(seed_demo.main(), 0)
        movies_n, halls_n, sessions_n, tickets_n = self.counts()
        self.assertEqual((movies_n, halls_n), (28, 5))
        self.assertGreater(sessions_n, 80)
        self.assertGreater(tickets_n, 0)
        admin = auth.login("admin", "admin123")
        self.assertEqual(auth.login("kassa", "kassa123").role, "cashier")
        self.assertIsNotNone(auth.login("buyer", "buyer123").client_id)
        self.assertTrue(session_service.list_sessions(admin))
        self.assertTrue(ticket_service.search_tickets(admin))
        with patch("builtins.print"):
            self.assertEqual(seed_demo.main(), 1)                 # повторный запуск ничего не дублирует
        self.assertEqual(self.counts()[0], 28)

    def test_demo_accounts_exist_even_if_database_is_not_empty(self):
        ok, _ = seed_demo.populate_default()
        self.assertTrue(ok)
        self.assertFalse(seed_demo.populate_default()[0])

    def test_changed_admin_password_is_reported_not_crashing(self):
        auth.ensure_default_admin()
        admin = auth.login("admin", "admin123")
        auth.change_own_password(admin, "admin123", "another-pass")
        ok, message = seed_demo.populate_default()
        self.assertFalse(ok)
        self.assertIn("пароль", message)


class OfferDemoDataTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch("database.connection.DB_PATH", Path(self._tmp.name) / "demo.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        posters = patch("services.movie_service.POSTERS_DIR", Path(self._tmp.name) / "posters")
        posters.start()
        self.addCleanup(posters.stop)
        auth.ensure_default_admin()

    def test_empty_database_is_filled_without_any_question(self):
        box = FakeMessagebox(True)
        app_main._offer_demo_data(None, box)
        self.assertFalse(seed_demo.database_is_empty())
        self.assertEqual(box.calls, [])                       # ни вопроса, ни окна-сообщения

    def test_no_question_when_data_already_exists(self):
        seed_demo.populate_default()
        box = FakeMessagebox(True)
        app_main._offer_demo_data(None, box)
        self.assertEqual(box.calls, [])

    def test_errors_are_shown_not_raised(self):
        box = FakeMessagebox(True)
        with patch("seed_demo.populate_default", side_effect=RuntimeError("boom")), self.assertLogs("cinema", "ERROR"):
            app_main._offer_demo_data(None, box)
        self.assertEqual(box.calls[-1][0], "error")


if __name__ == "__main__":
    unittest.main()
