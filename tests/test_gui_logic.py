"""Логика GUI без tkinter: форматирование, меню по ролям, лимит попыток входа."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from gui import formatting as fmt
from gui.login_guard import LoginAttemptLimiter
from gui.navigation import menu_for
from services.errors import ValidationError
from services.permissions import CurrentUser, Role

NB = "\u00a0"


def user(role, client_id=None):
    return CurrentUser(id=1, username="u", full_name="Тест", role=role, client_id=client_id)


def session(**kw):
    base = dict(id=1, session_date="2026-11-01", session_time="18:00", end_time="19:40",
                movie_title="Фильм", genre_name="Драма", age_rating="12+", hall_name="Зал 1",
                price=300.0, seats_free=7, seats_total=10, duration=100,
                description="Описание", poster_path=None)
    return {**base, **kw}


class FormattingTests(unittest.TestCase):
    def test_price(self):
        self.assertEqual(fmt.format_price(300), f"300{NB}₽")
        self.assertEqual(fmt.format_price(1200.0), f"1{NB}200{NB}₽")
        self.assertEqual(fmt.format_price(350.5), f"350,50{NB}₽")
        self.assertEqual(fmt.format_price("99.99"), f"99,99{NB}₽")

    def test_duration(self):
        self.assertEqual(fmt.format_duration(100), "1 ч 40 мин")
        self.assertEqual(fmt.format_duration(120), "2 ч")
        self.assertEqual(fmt.format_duration(45), "45 мин")

    def test_dates(self):
        self.assertEqual(fmt.shift_date("31.12.2026", 1), "01.01.2027")
        self.assertEqual(fmt.shift_date("2026-03-01", -1), "28.02.2026")
        self.assertEqual(fmt.normalize_date_input(" 2026-10-16 "), "16.10.2026")
        for bad in ("", "abc", "32.01.2026", None):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                fmt.normalize_date_input(bad)

    def test_user_caption_does_not_repeat_role(self):
        self.assertEqual(fmt.user_caption(user(Role.CASHIER)), "Тест · Кассир")
        admin = CurrentUser(id=1, username="admin", full_name="Администратор", role=Role.ADMIN)
        self.assertEqual(fmt.user_caption(admin), "Администратор")

    def test_roles(self):
        self.assertEqual(fmt.role_title("cashier"), "Кассир")
        self.assertEqual(fmt.role_title("unknown"), "unknown")

    def test_session_row_and_time_range(self):
        row = fmt.session_row(session())
        self.assertEqual(row[0], "18:00–19:40")
        self.assertEqual(row[1:5], ("Фильм", "Драма", "12+", "Зал 1"))
        self.assertEqual(row[6], "7 из 10")
        self.assertEqual(fmt.time_range(session(session_time="23:00", end_time="01:00")), "23:00–01:00 (+1 д)")

    def test_session_tag(self):
        start = datetime(2026, 11, 1, 18, 0)
        self.assertEqual(fmt.session_tag(session(), start - timedelta(hours=1)), "")
        self.assertEqual(fmt.session_tag(session(seats_free=0), start - timedelta(hours=1)), "soldout")
        self.assertEqual(fmt.session_tag(session(), start), "past")
        self.assertEqual(fmt.session_tag(session(seats_free=0), start + timedelta(hours=1)), "past")

    def test_session_details(self):
        title, info, description = fmt.session_details(session())
        self.assertEqual((title, description), ("Фильм", "Описание"))
        self.assertIn("1 ч 40 мин", info)
        self.assertIn("Зал: Зал 1", info)
        self.assertEqual(fmt.session_details(session(description=None))[2], "Описание не указано.")

    def test_poster_only_png_gif_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            png, jpg = os.path.join(tmp, "a.PNG"), os.path.join(tmp, "b.jpg")
            for p in (png, jpg):
                open(p, "wb").close()
            self.assertEqual(fmt.poster_path_if_displayable(png), png)
            self.assertIsNone(fmt.poster_path_if_displayable(jpg))                 # JPG без Pillow не показать
            self.assertIsNone(fmt.poster_path_if_displayable(os.path.join(tmp, "no.png")))
        self.assertIsNone(fmt.poster_path_if_displayable(None))


class NavigationTests(unittest.TestCase):
    def keys(self, u):
        return [item.key for item in menu_for(u)]

    def test_admin_sees_everything_except_own_tickets_without_client(self):
        self.assertEqual(self.keys(user(Role.ADMIN)),
                         ["dashboard", "tickets", "movies", "halls", "sessions", "reports", "users"])

    def test_cashier(self):
        self.assertEqual(self.keys(user(Role.CASHIER)), ["cash_home", "sale", "search", "refund", "history", "shift"])

    def test_viewer(self):
        self.assertEqual(self.keys(user(Role.VIEWER, client_id=5)),
                         ["buyer_home", "poster", "my_tickets", "orders", "profile"])
        self.assertEqual(self.keys(user(Role.VIEWER)), ["buyer_home", "poster", "profile"])   # без клиентской карточки

    def test_viewer_never_sees_staff_sections(self):
        hidden = {"dashboard", "tickets", "movies", "halls", "sessions", "reports", "users"}
        self.assertFalse(hidden & set(self.keys(user(Role.VIEWER, client_id=5))))


class LoginLimiterTests(unittest.TestCase):
    def setUp(self):
        self.t = datetime(2026, 10, 16, 12, 0, 0)
        self.limiter = LoginAttemptLimiter(max_attempts=3, lock_seconds=30, now=lambda: self.t)

    def test_locks_after_max_failures_and_unlocks_in_time(self):
        self.assertFalse(self.limiter.register_failure())
        self.assertFalse(self.limiter.register_failure())
        self.assertEqual(self.limiter.seconds_left(), 0)
        self.assertTrue(self.limiter.register_failure())
        self.assertEqual(self.limiter.seconds_left(), 30)
        self.t += timedelta(seconds=10)
        self.assertEqual(self.limiter.seconds_left(), 20)
        self.t += timedelta(seconds=21)
        self.assertEqual(self.limiter.seconds_left(), 0)
        self.assertFalse(self.limiter.register_failure())   # счётчик начат заново

    def test_success_resets(self):
        self.limiter.register_failure()
        self.limiter.register_failure()
        self.limiter.register_success()
        self.assertFalse(self.limiter.register_failure())


if __name__ == "__main__":
    unittest.main()


class AfishaFormattingTests(unittest.TestCase):
    def test_upcoming_times_hides_started_sessions(self):
        sessions = [{"session_time": "10:00", "started": True}, {"session_time": "13:30", "started": False},
                    {"session_time": "17:00", "started": False}]
        self.assertEqual(fmt.upcoming_times(sessions), "13:30 · 17:00")
        self.assertEqual(fmt.upcoming_times(sessions[:1]), "Сеансов больше нет")
        many = [{"session_time": f"1{i}:00", "started": False} for i in range(6)]
        self.assertEqual(fmt.upcoming_times(many), "10:00 · 11:00 · 12:00 · 13:00 …")

    def test_short_description(self):
        self.assertEqual(fmt.short_description(None), "Описание не указано.")
        self.assertEqual(fmt.short_description("  Коротко   и ясно "), "Коротко и ясно")
        long = fmt.short_description("слово " * 100, 50)
        self.assertTrue(long.endswith("…"))
        self.assertLessEqual(len(long), 51)

    def test_seats_caption(self):
        rows = [{"row_number": 3, "seats": [{"id": i, "seat_number": i} for i in range(1, 6)]},
                {"row_number": 4, "seats": [{"id": 10 + i, "seat_number": i} for i in range(1, 6)]}]
        self.assertEqual(fmt.seats_caption(rows, {5}), "Ряд 3, место 5")
        self.assertEqual(fmt.seats_caption(rows, {4, 5}), "Ряд 3, места 4 и 5")
        self.assertEqual(fmt.seats_caption(rows, {1, 2, 3, 11}), "Ряд 3, места 1, 2 и 3; ряд 4, место 1")
        self.assertEqual(fmt.seats_caption(rows, set()), "")

    def test_day_caption(self):
        from datetime import date
        today = date(2026, 10, 16)
        self.assertEqual(fmt.day_caption("2026-10-16", today), "Сегодня")
        self.assertEqual(fmt.day_caption("2026-10-17", today), "Завтра")
        self.assertEqual(fmt.day_caption("2026-10-23", today), "23.10 пт")

    def test_end_caption_shows_next_day(self):
        same = {"session_date": "2026-10-16", "end_date": "2026-10-16", "end_time": "19:40"}
        night = {"session_date": "2026-10-16", "end_date": "2026-10-17", "end_time": "01:10"}
        self.assertEqual(fmt.end_caption(same), "до 19:40")
        self.assertEqual(fmt.end_caption(night), "до 01:10 (17.10)")
