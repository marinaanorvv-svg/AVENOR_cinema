"""Проверка отчётов и экспорта в CSV. Запуск:  python -m unittest tests.test_reports -v"""
import csv
import io
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from services import hall_service as halls
from services import report_service as reports
from services import session_service as sessions
from services import ticket_service as tickets
from services.errors import PermissionDenied, ValidationError
from tests.base import CatalogTestCase

T = lambda day, hour=12, month=10: datetime(2026, month, day, hour, 0)   # короткая запись времени


class ReportTests(CatalogTestCase):
    """Сценарий (деньги — по кассовому методу):

    сеансы: S1 М1/зал A 05.10 18:00 300₽ | S2 М1/зал A 06.10 18:00 400₽
            S3 М2/зал B 06.10 12:00 200₽ | S4 М2/зал B 25.10 12:00 250₽ (будущий)
    02.10 — 3 билета на S1;  03.10 — 2 на S2 и 1 на S3;  03.10 16:00 — возврат 1 билета S1;
    04.10 — 1 билет на S4.
    """

    def at(self, when):
        return patch("services.clock.now", return_value=when)

    def setUp(self):
        super().setUp()
        self.hall_a = self.hall("Зал A", 2, 5)                                  # 10 мест
        self.hall_b = halls.create_hall(self.admin, "Зал B", 1, 4, db_path=self.db)   # 4 места
        self.m1, self.m2 = self.movie("Фильм 1", duration=100), self.movie("Фильм 2", duration=90)
        seats = {h: [s["id"] for row in halls.get_hall_scheme(self.admin, h, self.db)["rows"]
                     for s in row["seats"]] for h in (self.hall_a, self.hall_b)}

        with self.at(T(1, 10)):
            mk = lambda m, h, d, tm, p: sessions.create_session(self.admin, m, h, f"2026-10-{d}", tm, p, self.db)
            self.s1 = mk(self.m1, self.hall_a, "05", "18:00", 300)
            self.s2 = mk(self.m1, self.hall_a, "06", "18:00", 400)
            self.s3 = mk(self.m2, self.hall_b, "06", "12:00", 200)
            self.s4 = mk(self.m2, self.hall_b, "25", "12:00", 250)

        def sell(session_id, hall, n, start=0):
            return [tickets.sell_ticket(self.cashier, session_id, seats[hall][start + i],
                                        {"full_name": f"Клиент {session_id}-{start + i}"}, self.db)
                    for i in range(n)]

        with self.at(T(2, 9)):
            first = sell(self.s1, self.hall_a, 3)
        with self.at(T(3, 15)):
            sell(self.s2, self.hall_a, 2)
            sell(self.s3, self.hall_b, 1)
        with self.at(T(3, 16)):
            tickets.refund_ticket(self.cashier, first[0]["id"], self.db)
        with self.at(T(4, 11)):
            sell(self.s4, self.hall_b, 1)

    def rev(self, d1="2026-10-01", d2="2026-10-31"):
        return reports.revenue_report(self.admin, d1, d2, self.db)

    def att(self, now=T(20), d1="2026-10-01", d2="2026-10-31", **kw):
        with self.at(now):
            return reports.attendance_report(self.admin, d1, d2, db_path=self.db, **kw)

    # --- выручка
    def test_revenue_summary_and_by_day(self):
        r = self.rev()
        self.assertEqual(r["summary"], {"tickets_sold": 7, "sales_amount": 2150.0,
                                        "tickets_returned": 1, "refund_amount": 300.0,
                                        "net_revenue": 1850.0})
        days = {row["date"]: row for row in r["tables"]["by_day"]["rows"]}
        self.assertEqual(len(days), 31)                                     # нулевые дни тоже есть
        self.assertEqual(days["2026-10-01"]["net_revenue"], 0.0)
        self.assertEqual((days["2026-10-02"]["tickets_sold"], days["2026-10-02"]["net_revenue"]), (3, 900.0))
        d3 = days["2026-10-03"]
        self.assertEqual((d3["tickets_sold"], d3["sales_amount"], d3["tickets_returned"],
                          d3["refund_amount"], d3["net_revenue"]), (3, 1000.0, 1, 300.0, 700.0))

    def test_revenue_by_movie_and_hall(self):
        r = self.rev()
        movies_ = {x["movie"]: x for x in r["tables"]["by_movie"]["rows"]}
        self.assertEqual((movies_["Фильм 1"]["tickets_sold"], movies_["Фильм 1"]["net_revenue"]), (5, 1400.0))
        self.assertEqual((movies_["Фильм 2"]["tickets_sold"], movies_["Фильм 2"]["net_revenue"]), (2, 450.0))
        self.assertEqual([x["movie"] for x in r["tables"]["by_movie"]["rows"]], ["Фильм 1", "Фильм 2"])  # по убыванию
        halls_ = {x["hall"]: x for x in r["tables"]["by_hall"]["rows"]}
        self.assertEqual(halls_["Зал A"]["net_revenue"], 1400.0)
        self.assertEqual(halls_["Зал B"]["net_revenue"], 450.0)
        for name in ("by_day", "by_movie", "by_hall"):   # все разрезы сходятся с итогом
            self.assertEqual(r["tables"][name]["totals"]["net_revenue"], 1850.0, name)

    def test_cash_method_period_boundaries(self):
        r = self.rev("2026-10-03", "2026-10-03")
        # покупки 02.10 не входят, а возврат билета, купленного 02.10, — входит
        self.assertEqual(r["summary"], {"tickets_sold": 3, "sales_amount": 1000.0,
                                        "tickets_returned": 1, "refund_amount": 300.0,
                                        "net_revenue": 700.0})
        empty = self.rev("2026-09-01", "2026-09-30")
        self.assertEqual(empty["summary"]["net_revenue"], 0.0)
        self.assertEqual(empty["tables"]["by_movie"]["rows"], [])

    # --- посещаемость
    def test_attendance_counts_only_started_sessions_by_default(self):
        r = self.att()
        self.assertEqual(r["summary"], {"sessions": 3, "visitors": 5, "capacity": 24,
                                        "occupancy_percent": 20.8})
        rows = {x["session_id"]: x for x in r["tables"]["by_session"]["rows"]}
        self.assertEqual(set(rows), {self.s1, self.s2, self.s3})           # будущий S4 не учтён
        self.assertEqual((rows[self.s1]["visitors"], rows[self.s1]["occupancy_percent"]), (2, 20.0))  # 3 − 1 возврат
        movies_ = {x["movie"]: x for x in r["tables"]["by_movie"]["rows"]}
        self.assertEqual((movies_["Фильм 1"]["sessions"], movies_["Фильм 1"]["visitors"],
                          movies_["Фильм 1"]["occupancy_percent"]), (2, 4, 20.0))
        self.assertEqual(movies_["Фильм 2"]["occupancy_percent"], 25.0)

    def test_attendance_include_upcoming(self):
        r = self.att(include_upcoming=True)
        self.assertEqual((r["summary"]["sessions"], r["summary"]["visitors"], r["summary"]["capacity"]),
                         (4, 6, 28))

    def test_attendance_period_filter_and_empty(self):
        r = self.att(d1="2026-10-06", d2="2026-10-06")
        self.assertEqual({x["session_id"] for x in r["tables"]["by_session"]["rows"]}, {self.s2, self.s3})
        empty = self.att(d1="2026-09-01", d2="2026-09-02")
        self.assertEqual(empty["summary"], {"sessions": 0, "visitors": 0, "capacity": 0,
                                            "occupancy_percent": 0.0})

    # --- период и права
    def test_period_validation(self):
        for d1, d2 in (("2026-10-31", "2026-10-01"), ("abc", "2026-10-01"), (None, "2026-10-01"),
                       ("2026-01-01", "2027-12-31"), ("2026-13-01", "2026-13-02")):
            with self.assertRaises(ValidationError, msg=(d1, d2)):
                self.rev(d1, d2)
            with self.assertRaises(ValidationError, msg=(d1, d2)):
                reports.attendance_report(self.admin, d1, d2, db_path=self.db)
        self.rev("01.10.2026", "31.10.2026")   # российский формат дат тоже принимается

    def test_only_admin_can_view_reports(self):
        for actor in (self.cashier, self.viewer):
            with self.assertRaises(PermissionDenied):
                reports.revenue_report(actor, "2026-10-01", "2026-10-31", self.db)
            with self.assertRaises(PermissionDenied):
                reports.attendance_report(actor, "2026-10-01", "2026-10-31", db_path=self.db)
            with self.assertRaises(PermissionDenied):
                reports.save_report_csv(actor, self.rev(), os.devnull)

    # --- CSV
    def parse(self, text):
        return list(csv.reader(io.StringIO(text), delimiter=";"))

    def test_csv_revenue_by_day(self):
        rows = self.parse(reports.report_to_csv(self.rev(), "by_day"))
        self.assertEqual(rows[0], ["Дата", "Продано, шт.", "Продажи, ₽", "Возвращено, шт.",
                                   "Возвраты, ₽", "Выручка, ₽"])
        self.assertEqual(len(rows), 1 + 31 + 1)                             # шапка + дни + «Итого»
        self.assertEqual(rows[3], ["2026-10-03", "3", "1000,00", "1", "300,00", "700,00"])   # десятичная запятая
        self.assertEqual(rows[-1], ["Итого", "7", "2150,00", "1", "300,00", "1850,00"])

    def test_csv_attendance_and_default_table(self):
        r = self.att()
        rows = self.parse(reports.report_to_csv(r))                         # по умолчанию — первая таблица
        self.assertEqual(rows[0][0:3], ["Дата", "Время", "Фильм"])
        self.assertEqual(rows[-1][0], "Итого")
        with self.assertRaises(ValidationError):
            reports.report_to_csv(r, "no_such_table")

    def test_csv_formula_injection_is_neutralized(self):
        with self.at(T(1, 10)):
            evil = self.movie('=HYPERLINK("http://evil")', duration=60)
            sid = sessions.create_session(self.admin, evil, self.hall_b, "2026-10-08", "20:00", 100, self.db)
        seat = halls.get_hall_scheme(self.admin, self.hall_b, self.db)["rows"][0]["seats"][0]["id"]
        with self.at(T(4, 12)):
            tickets.sell_ticket(self.cashier, sid, seat, {"full_name": "X"}, self.db)
        text = reports.report_to_csv(self.rev(), "by_movie")
        cells = [row[0] for row in self.parse(text)[1:-1]]
        self.assertIn("'=HYPERLINK(\"http://evil\")", cells)
        self.assertFalse(any(c.startswith("=") for c in cells))

    def test_save_csv_file_has_bom_and_handles_bad_path(self):
        path = os.path.join(self._tmp.name, "report.csv")
        reports.save_report_csv(self.admin, self.rev(), path, "by_movie")
        with open(path, "rb") as f:
            self.assertTrue(f.read().startswith(b"\xef\xbb\xbf"))
        with self.assertRaises(ValidationError):
            reports.save_report_csv(self.admin, self.rev(), os.path.join(self._tmp.name, "нет", "r.csv"))


if __name__ == "__main__":
    unittest.main()
