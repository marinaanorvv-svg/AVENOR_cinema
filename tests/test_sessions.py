"""Проверка сеансов и расписания. Запуск:  python -m unittest tests.test_sessions -v"""
import unittest
from datetime import datetime
from unittest.mock import patch

from database import crud
from database.connection import transaction
from services import session_service as sessions
from services.errors import PermissionDenied, ValidationError
from tests.base import CatalogTestCase

FAKE_NOW = datetime(2026, 10, 16, 12, 0)


class SessionTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("services.session_service._now", return_value=FAKE_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.movie_id = self.movie("Длинный", duration=120)   # 2 часа
        self.hall_a = self.hall("Зал A", 2, 5)                 # 10 мест
        self.hall_b = self.hall("Зал B", 2, 5)

    def make(self, time="18:00", date="2026-11-01", hall=None, movie=None, price=300):
        return sessions.create_session(self.admin, movie or self.movie_id, hall or self.hall_a,
                                       date, time, price, self.db)

    def sell(self, session_id, status="sold"):
        """Билет в обход сервиса билетов (его ещё нет) — для проверки правил блокировки."""
        with transaction(self.db) as conn:
            hall_id = crud.get_session(conn, session_id)["hall_id"]
            seat_id = crud.list_seats_by_hall(conn, hall_id)[0]["id"]
            client = crud.create_client(conn, "Клиент")
            return crud.create_ticket(conn, session_id, seat_id, client, status)

    # --- создание
    def test_create_normalizes_input(self):
        sid = sessions.create_session(self.admin, self.movie_id, self.hall_a,
                                      "20.11.2026", "9:05", "350,5", self.db)
        s = sessions.get_session(self.viewer, sid, self.db)
        self.assertEqual((s["session_date"], s["session_time"], s["price"]),
                         ("2026-11-20", "09:05", 350.5))
        self.assertEqual(s["end_time"], "11:05")
        self.assertEqual((s["movie_title"], s["hall_name"]), ("Длинный", "Зал A"))

    def test_invalid_input(self):
        base = dict(movie_id=self.movie_id, hall_id=self.hall_a,
                    session_date="2026-11-01", session_time="18:00", price=300)
        bad = [dict(session_date="2026-13-40"), dict(session_date="abc"), dict(session_date=None),
               dict(session_time="25:00"), dict(session_time="18-00"),
               dict(price=-1), dict(price="abc"), dict(price=float("nan")), dict(price=True),
               dict(price=100001), dict(movie_id=9999), dict(hall_id=9999), dict(movie_id="x")]
        for patch_ in bad:
            with self.assertRaises(ValidationError, msg=repr(patch_)):
                sessions.create_session(self.admin, db_path=self.db, **{**base, **patch_})

    def test_past_sessions_rejected(self):
        with self.assertRaises(ValidationError):
            self.make(time="11:00", date="2026-10-16")
        self.make(time="13:00", date="2026-10-16")   # позже «сейчас» — можно

    # --- пересечения
    def test_overlap_rules_with_cleaning_break(self):
        self.make("18:00")   # 18:00–20:00, зал освобождается в 20:15
        for bad in ("19:00", "17:00", "20:10", "15:50"):   # 15:50 + 2ч + 15м = 18:05 > 18:00
            with self.assertRaises(ValidationError, msg=bad):
                self.make(bad)
        self.make("20:15")   # ровно после перерыва
        self.make("15:45")   # заканчивается (с перерывом) ровно в 18:00
        self.make("18:00", hall=self.hall_b)   # другой зал — можно

    def test_overlap_across_midnight(self):
        self.make("23:00", date="2026-11-01")   # идёт до 01:00, зал свободен с 01:15
        with self.assertRaises(ValidationError):
            self.make("01:00", date="2026-11-02")
        self.make("01:15", date="2026-11-02")

    # --- изменение
    def test_update_price_and_time(self):
        sid = self.make("18:00")
        sessions.update_session(self.admin, sid, self.db, price="450", session_time="19:00")
        s = sessions.get_session(self.admin, sid, self.db)
        self.assertEqual((s["price"], s["session_time"]), (450.0, "19:00"))
        sessions.update_session(self.admin, sid, self.db, session_time="19:00")  # без изменений — ок

    def test_update_overlap_ignores_self_but_not_others(self):
        a, b = self.make("18:00"), self.make("21:00")
        sessions.update_session(self.admin, a, self.db, session_time="18:30")   # сам себе не мешает
        with self.assertRaises(ValidationError):
            sessions.update_session(self.admin, b, self.db, session_time="19:00")

    def test_update_unknown_field_and_missing_session(self):
        sid = self.make()
        with self.assertRaises(ValidationError):
            sessions.update_session(self.admin, sid, self.db, id=5)
        with self.assertRaises(ValidationError):
            sessions.update_session(self.admin, 9999, self.db, price=1)

    def test_past_check_only_when_time_changes(self):
        sid = self.make("13:00", date="2026-10-16")
        with self.assertRaises(ValidationError):
            sessions.update_session(self.admin, sid, self.db, session_time="11:00")
        with patch("services.session_service._now", return_value=datetime(2026, 10, 16, 15, 0)):
            sessions.update_session(self.admin, sid, self.db, price=999)   # цена у «уже начавшегося» — ок

    def test_sold_tickets_lock_session(self):
        sid = self.make()
        self.sell(sid, "sold")
        with self.assertRaises(ValidationError) as ctx:
            sessions.update_session(self.admin, sid, self.db, session_time="19:00")
        self.assertIn("возврат", str(ctx.exception))

    def test_returned_tickets_lock_only_hall_and_price(self):
        sid = self.make()
        self.sell(sid, "returned")
        for locked in (dict(price=1), dict(hall_id=self.hall_b)):
            with self.assertRaises(ValidationError):
                sessions.update_session(self.admin, sid, self.db, **locked)
        sessions.update_session(self.admin, sid, self.db, session_time="19:00")

    def test_delete(self):
        free, used = self.make("10:00"), self.make("14:00")
        self.sell(used, "returned")
        sessions.delete_session(self.admin, free, self.db)
        with self.assertRaises(ValidationError):
            sessions.delete_session(self.admin, used, self.db)
        with self.assertRaises(ValidationError):
            sessions.delete_session(self.admin, free, self.db)   # уже удалён

    # --- чтение
    def test_list_filters_and_free_seats(self):
        s1 = self.make("10:00", date="2026-11-01")
        self.make("12:30", date="2026-11-02")
        self.sell(s1)
        day = sessions.list_sessions(self.viewer, date="01.11.2026", db_path=self.db)
        self.assertEqual([s["id"] for s in day], [s1])
        self.assertEqual((day[0]["seats_total"], day[0]["seats_sold"], day[0]["seats_free"]), (10, 1, 9))
        period = sessions.list_sessions(self.viewer, date_from="2026-11-01", date_to="2026-11-02", db_path=self.db)
        self.assertEqual(len(period), 2)
        self.assertEqual(len(sessions.list_sessions(self.viewer, hall_id=self.hall_b, db_path=self.db)), 0)

    def test_schedule_for_date_grouped_by_movie(self):
        other = self.movie("Анимация", duration=90)
        self.make("10:00", date="2026-11-01")
        self.make("14:00", date="2026-11-01")
        self.make("11:00", date="2026-11-01", hall=self.hall_b, movie=other)
        self.make("10:00", date="2026-11-05")
        board = sessions.get_schedule_for_date(self.viewer, "2026-11-01", self.db)
        self.assertEqual([e["movie"]["title"] for e in board], ["Анимация", "Длинный"])
        self.assertEqual([x["session_time"] for x in board[1]["sessions"]], ["10:00", "14:00"])
        self.assertEqual(sessions.get_schedule_for_date(self.viewer, "2026-12-31", self.db), [])

    # --- права
    def test_permissions(self):
        for actor in (self.cashier, self.viewer):
            with self.assertRaises(PermissionDenied):
                sessions.create_session(actor, self.movie_id, self.hall_a, "2026-11-01", "10:00", 100, self.db)
            with self.assertRaises(PermissionDenied):
                sessions.delete_session(actor, 1, self.db)
            sessions.list_sessions(actor, db_path=self.db)   # афиша доступна всем ролям


if __name__ == "__main__":
    unittest.main()


class AutoScheduleTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("services.session_service._now", return_value=FAKE_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.movie_id = self.movie("Фильм", duration=120)
        self.hall_a = self.hall("Зал A", 2, 5)
        self.hall_b = self.hall("Зал B", 2, 5)

    def run_auto(self, **kw):
        args = dict(movie_id=self.movie_id, date_from="2026-11-01", days=3, per_day=2, price=350)
        args.update(kw)
        return sessions.auto_schedule(self.admin, db_path=self.db, **args)

    def test_creates_sessions_without_overlaps(self):
        result = self.run_auto()
        self.assertEqual(result, {"created": 6, "skipped": 0})
        listed = sessions.list_sessions(self.admin, date_from="2026-11-01", date_to="2026-11-03", db_path=self.db)
        self.assertEqual(len(listed), 6)
        self.assertEqual(len({(s["session_date"], s["session_time"], s["hall_id"]) for s in listed}), 6)

    def test_second_run_adds_other_times_and_never_overlaps(self):
        self.run_auto(days=1)
        self.run_auto(days=1)                       # зал занят — программа ищет другое время или другой зал
        listed = sessions.list_sessions(self.admin, date="2026-11-01", db_path=self.db)
        for hall in (self.hall_a, self.hall_b):
            own = sorted(s["session_time"] for s in listed if s["hall_id"] == hall)
            for first, second in zip(own, own[1:]):
                self.assertGreaterEqual(int(second[:2]) * 60 + int(second[3:]) - int(first[:2]) * 60 - int(first[3:]),
                                        120 + sessions.CLEANING_BREAK_MIN)

    def test_past_time_is_skipped(self):
        result = sessions.auto_schedule(self.admin, self.movie_id, "2026-10-16", 1, 3, 300, self.db)   # «сейчас» 12:00
        listed = sessions.list_sessions(self.admin, date="2026-10-16", db_path=self.db)
        self.assertTrue(all(s["session_time"] >= "12:00" for s in listed))
        self.assertEqual(result["created"], len(listed))

    def test_validation_and_permissions(self):
        with self.assertRaises(ValidationError):
            self.run_auto(days=0)
        with self.assertRaises(ValidationError):
            self.run_auto(per_day=99)
        with self.assertRaises(ValidationError):
            self.run_auto(date_from="не дата")
        with self.assertRaises(PermissionDenied):
            sessions.auto_schedule(self.cashier, self.movie_id, "2026-11-01", 1, 1, 300, self.db)

    def test_midnight_crossing_is_shown_as_next_day(self):
        sid = self.make_late()
        s = sessions.get_session(self.admin, sid, self.db)
        self.assertEqual((s["end_time"], s["end_date"]), ("00:30", "2026-11-02"))

    def make_late(self):
        movie = self.movie("Ночной", duration=150)
        return sessions.create_session(self.admin, movie, self.hall_a, "2026-11-01", "22:00", 300, self.db)
