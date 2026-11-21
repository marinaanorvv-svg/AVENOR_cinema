"""Тесты административных функций: главная панель, билеты, отмена сеансов, отчёты по кассирам, пользователи.

Запуск:  python -m unittest tests.test_admin -v
"""
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests import fake_tk
from tests import test_gui_screens as screens
from tests import test_gui_smoke as smoke
from tests.base import CatalogTestCase

from database import crud
from database.connection import connection, get_connection
from database.schema import create_schema
from services import admin_service as admin
from services import hall_service as halls
from services import auth_service as auth
from services import report_service as reports
from services import session_service as sessions
from services import ticket_service as tickets
from services.errors import PermissionDenied, ValidationError
from services.permissions import Role

NOW = datetime(2026, 10, 16, 12, 0)


def setUpModule():
    smoke.setUpModule()


def tearDownModule():
    smoke.tearDownModule()


class AdminWorld(CatalogTestCase):
    """Фильм, зал 2×5, сеанс 17.10 18:00 за 300 ₽; «сейчас» — 16.10.2026 12:00."""

    def setUp(self):
        super().setUp()
        patcher = patch("services.clock.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.movie_id = self.movie("Дюна", duration=155)
        self.hall_id = self.hall("Зал 1", rows=2, per_row=5, vip="2")
        self.session_id = sessions.create_session(self.admin, self.movie_id, self.hall_id, "2026-10-17", "18:00", 300,
                                                  db_path=self.db)
        scheme = halls.get_hall_scheme(self.admin, self.hall_id, self.db)
        self.seats = [s["id"] for row in scheme["rows"] for s in row["seats"]]

    def sell(self, index, actor=None, name=None):
        return tickets.sell_ticket(actor or self.cashier, self.session_id, self.seats[index],
                                   {"full_name": name or f"Клиент {index}"}, self.db)


class PermissionTests(AdminWorld):
    def test_staff_and_viewer_are_denied_at_service_level(self):
        calls = (lambda a: admin.dashboard(a, self.db), lambda a: admin.search_tickets(a, db_path=self.db),
                 lambda a: admin.list_sessions(a, db_path=self.db), lambda a: admin.cancel_session(a, self.session_id, self.db),
                 lambda a: admin.list_genres_with_counts(a, self.db), lambda a: admin.list_users(a, db_path=self.db),
                 lambda a: admin.update_user_profile(a, 1, "abc", "Имя", self.db),
                 lambda a: admin.assign_role(a, 1, Role.CASHIER, self.db),
                 lambda a: reports.cashier_report(a, "2026-10-01", "2026-10-31", self.db))
        for actor in (self.cashier, self.viewer):
            for call in calls:
                with self.assertRaises(PermissionDenied):
                    call(actor)
        for call in calls[:5]:
            call(self.admin)   # у администратора доступ есть


class DashboardTests(AdminWorld):
    def test_numbers_come_from_database(self):
        empty = admin.dashboard(self.admin, self.db)
        self.assertEqual((empty["movies"], empty["halls"], empty["active_sessions"], empty["tickets_today"],
                          empty["revenue_today"], empty["users"]), (1, 1, 1, 0, 0.0, 3))
        self.sell(0)
        t2 = self.sell(1)
        data = admin.dashboard(self.admin, self.db)
        self.assertEqual((data["tickets_today"], data["revenue_today"]), (2, 600.0))
        tickets.refund_ticket(self.admin, t2["id"], self.db)
        data = admin.dashboard(self.admin, self.db)
        self.assertEqual((data["tickets_today"], data["returns_today"], data["revenue_today"]), (2, 1, 300.0))
        self.assertEqual(len(data["series"]), 7)
        self.assertEqual(data["series"][-1], {"date": "2026-10-16", "tickets": 1, "revenue": 300.0})
        self.assertEqual(data["upcoming"][0]["sold"], 1)
        self.assertEqual([r["status"] for r in data["recent_sales"]], ["returned", "sold"])

    def test_dashboard_matches_revenue_report(self):
        self.sell(0)
        t = self.sell(1)
        tickets.refund_ticket(self.admin, t["id"], self.db)
        report = reports.revenue_report(self.admin, "2026-10-16", "2026-10-16", self.db)
        self.assertEqual(admin.dashboard(self.admin, self.db)["revenue_today"], report["summary"]["net_revenue"])

    def test_finished_and_cancelled_sessions_are_not_active(self):
        admin.cancel_session(self.admin, self.session_id, self.db)
        self.assertEqual(admin.dashboard(self.admin, self.db)["active_sessions"], 0)
        self.assertEqual(admin.dashboard(self.admin, self.db)["upcoming"], [])


class TicketSearchTests(AdminWorld):
    def test_filters(self):
        a = self.sell(0, name="Иван Петров")
        b = self.sell(1, name="Мария")
        other_movie = self.movie("Другой")
        s2 = sessions.create_session(self.admin, other_movie, self.hall_id, "2026-10-18", "12:00", 200, db_path=self.db)
        c = tickets.sell_ticket(self.cashier, s2, self.seats[2], {"full_name": "Иван Сидоров"}, self.db)
        tickets.refund_ticket(self.admin, b["id"], self.db)
        ids = lambda **kw: sorted(t["id"] for t in admin.search_tickets(self.admin, db_path=self.db, **kw))
        self.assertEqual(ids(), sorted([a["id"], b["id"], c["id"]]))
        self.assertEqual(ids(ticket_id=str(a["id"])), [a["id"]])
        self.assertEqual(ids(client="иван"), sorted([a["id"], c["id"]]))
        self.assertEqual(ids(movie_id=other_movie), [c["id"]])
        self.assertEqual(ids(status="returned"), [b["id"]])
        self.assertEqual(ids(session_from="18.10.2026"), [c["id"]])
        self.assertEqual(ids(session_to="2026-10-17"), sorted([a["id"], b["id"]]))
        self.assertEqual(ids(bought_from="16.10.2026", bought_to="16.10.2026"), sorted([a["id"], b["id"], c["id"]]))
        self.assertEqual(ids(bought_from="17.10.2026"), [])
        item = admin.search_tickets(self.admin, ticket_id=a["id"], db_path=self.db)[0]
        self.assertEqual((item["seller_label"], item["price"], item["hall_name"]), ("cash", 300.0, "Зал 1"))

    def test_bad_input(self):
        for kw in ({"ticket_id": "abc"}, {"status": "x"}, {"session_from": "32.13.2026"},
                   {"bought_from": "2026-10-20", "bought_to": "2026-10-01"}):
            with self.assertRaises(ValidationError):
                admin.search_tickets(self.admin, db_path=self.db, **kw)


class CancelSessionTests(AdminWorld):
    def test_cancel_refunds_everything_and_hides_session(self):
        for i in range(3):
            self.sell(i)
        result = admin.cancel_session(self.admin, self.session_id, self.db)
        self.assertEqual(result, {"refunded": 3, "amount": 900.0})
        with connection(self.db) as conn:
            self.assertEqual(crud.count_tickets_by_session(conn, self.session_id, "sold"), 0)
            self.assertEqual(crud.count_tickets_by_session(conn, self.session_id, "returned"), 3)   # история цела
        self.assertEqual(sessions.list_sessions(self.cashier, db_path=self.db), [])                # нет в афише
        shown = admin.list_sessions(self.admin, db_path=self.db)
        self.assertTrue(shown[0]["cancelled"])
        self.assertEqual(admin.list_sessions(self.admin, include_cancelled=False, db_path=self.db), [])
        with self.assertRaises(ValidationError):                                                    # продажа закрыта
            self.sell(4)
        with self.assertRaises(ValidationError):
            sessions.update_session(self.admin, self.session_id, db_path=self.db, price=100)
        with self.assertRaises(ValidationError):
            admin.cancel_session(self.admin, self.session_id, self.db)
        report = reports.revenue_report(self.admin, "2026-10-16", "2026-10-16", self.db)            # возвраты в выручке
        self.assertEqual((report["summary"]["tickets_returned"], report["summary"]["net_revenue"]), (3, 0.0))

    def test_started_session_cannot_be_cancelled(self):
        with patch("services.clock.now", return_value=datetime(2026, 10, 17, 18, 30)):
            with self.assertRaises(ValidationError):
                admin.cancel_session(self.admin, self.session_id, self.db)

    def test_cancelled_slot_does_not_block_overlap_check_for_other_times(self):
        admin.cancel_session(self.admin, self.session_id, self.db)
        sessions.create_session(self.admin, self.movie_id, self.hall_id, "2026-10-17", "19:00", 300, db_path=self.db)


class ReportTests(AdminWorld):
    def test_cashier_report_groups_by_seller(self):
        self.sell(0)
        t = self.sell(1)
        with self.assertRaises(PermissionDenied):          # администратор билеты не продаёт
            tickets.sell_ticket(self.admin, self.session_id, self.seats[2], {"full_name": "У админа"}, self.db)
        self.viewer = auth.login("view", "secret1", self.db)
        tickets.sell_ticket(self.viewer, self.session_id, self.seats[3], {"full_name": "игнор"}, self.db)
        tickets.refund_ticket(self.admin, t["id"], self.db)
        report = reports.cashier_report(self.admin, "2026-10-16", "2026-10-16", self.db)
        rows = {r["cashier"]: r for r in report["tables"]["by_cashier"]["rows"]}
        self.assertEqual(rows["cash (cash)"]["tickets_sold"], 2)
        self.assertEqual((rows["cash (cash)"]["tickets_returned"], rows["cash (cash)"]["net_revenue"]), (1, 300.0))
        self.assertNotIn("Администратор (admin)", rows)
        self.assertEqual(rows["Покупатели (онлайн)"]["tickets_sold"], 1)
        self.assertEqual(report["summary"]["tickets_sold"], 3)
        self.assertIn("Сотрудник", reports.report_to_csv(report))

    def test_old_tickets_without_seller_are_not_lost(self):
        conn = get_connection(self.db)
        conn.execute("INSERT INTO clients (full_name) VALUES ('Старый')")
        conn.execute("INSERT INTO tickets (session_id, seat_id, client_id, purchase_date) VALUES (?, ?, 1, '2026-10-16 10:00:00')",
                     (self.session_id, self.seats[0]))
        conn.commit()
        conn.close()
        rows = reports.cashier_report(self.admin, "2026-10-16", "2026-10-16", self.db)["tables"]["by_cashier"]["rows"]
        self.assertEqual([r["cashier"] for r in rows], ["Не определён"])

    def test_attendance_has_hall_occupancy_and_top_sessions(self):
        for i in range(3):
            self.sell(i)
        later = NOW.replace(day=18)
        with patch("services.clock.now", return_value=later):
            r = reports.attendance_report(self.admin, "2026-10-17", "2026-10-17", db_path=self.db)
        hall = r["tables"]["by_hall"]["rows"][0]
        self.assertEqual((hall["hall"], hall["visitors"], hall["capacity"], hall["occupancy_percent"]), ("Зал 1", 3, 10, 30.0))
        self.assertEqual(r["tables"]["top_sessions"]["rows"][0]["visitors"], 3)
        self.assertIn("Зрителей", reports.report_to_csv(r, "top_sessions"))


class UserAdminTests(AdminWorld):
    def test_search_and_filters(self):
        names = lambda **kw: [u["username"] for u in admin.list_users(self.admin, db_path=self.db, **kw)]
        self.assertEqual(names(), ["admin", "cash", "view"])
        self.assertEqual(names(search="CA"), ["cash"])
        self.assertEqual(names(role=Role.VIEWER), ["view"])
        auth.set_user_active(self.admin, self.cashier.id, False, self.db)
        self.assertEqual(names(active=False), ["cash"])
        self.assertNotIn("password_hash", admin.list_users(self.admin, db_path=self.db)[0])

    def test_update_profile_and_duplicate_login(self):
        admin.update_user_profile(self.admin, self.cashier.id, "kassir2", "Новое Имя", self.db)
        self.assertEqual(auth.login("kassir2", "secret1", self.db).full_name, "Новое Имя")
        with self.assertRaisesRegex(ValidationError, "уже существует"):
            admin.update_user_profile(self.admin, self.cashier.id, "admin", "X", self.db)
        with self.assertRaises(ValidationError):
            admin.update_user_profile(self.admin, self.cashier.id, "a b", "X", self.db)

    def test_role_protection(self):
        with self.assertRaisesRegex(ValidationError, "собственную"):
            admin.assign_role(self.admin, self.admin.id, Role.CASHIER, self.db)
        second = auth.create_user_account(self.admin, "boss2", "secret1", Role.ADMIN, "Второй", db_path=self.db)
        admin.assign_role(self.admin, second, Role.CASHIER, self.db)   # админов осталось двое -> можно
        with self.assertRaises(ValidationError):                       # а теперь админ один
            auth.set_user_active(self.admin, self.admin.id, False, self.db)

    def test_cashier_becoming_viewer_gets_client_card(self):
        admin.assign_role(self.admin, self.cashier.id, Role.VIEWER, self.db)
        user = auth.login("cash", "secret1", self.db)
        self.assertEqual(user.role, Role.VIEWER)
        self.assertIsNotNone(user.client_id)
        self.assertEqual(tickets.list_my_tickets(user, self.db), [])


class SchemaMigrationTests(unittest.TestCase):
    def test_old_database_gets_new_columns_and_keeps_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, movie_id INTEGER, hall_id INTEGER,
                    session_date TEXT, session_time TEXT, price REAL);
                CREATE TABLE tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, seat_id INTEGER,
                    client_id INTEGER, purchase_date TEXT, status TEXT DEFAULT 'sold');
                INSERT INTO sessions (movie_id, hall_id, session_date, session_time, price) VALUES (1, 1, '2026-10-17', '18:00', 300);
                INSERT INTO tickets (session_id, seat_id, client_id, purchase_date) VALUES (1, 1, 1, '2026-10-16 10:00:00');""")
            conn.commit()
            create_schema(conn)
            cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
            self.assertIn("is_cancelled", cols("sessions"))
            self.assertIn("seller_id", cols("tickets"))
            self.assertEqual(conn.execute("SELECT is_cancelled FROM sessions").fetchone()[0], 0)
            self.assertIsNone(conn.execute("SELECT seller_id FROM tickets").fetchone()[0])
            conn.close()


class SaleRecordsSellerTests(AdminWorld):
    """Продажа кассира и покупателя работает как раньше; добавлена только запись «кто продал»."""

    def test_sale_flows_unchanged(self):
        t = self.sell(0)
        self.assertEqual((t["status"], t["price"], t["seat_label"]), ("sold", 300.0, "ряд 1, место 1"))
        viewer = auth.login("view", "secret1", self.db)
        mine = tickets.sell_ticket(viewer, self.session_id, self.seats[1], "ignored", self.db)
        self.assertEqual(mine["client_id"], viewer.client_id)
        with connection(self.db) as conn:
            self.assertEqual(crud.get_ticket(conn, t["id"])["seller_id"], self.cashier.id)
            self.assertEqual(crud.get_ticket(conn, mine["id"])["seller_id"], viewer.id)


# ------------------------------------------------------------------ экраны

class AdminScreens(screens.ScreenBase):
    def test_main_frame_routes_by_role(self):
        gui_main = smoke.gui["main_frame"]
        frame = gui_main.MainFrame(fake_tk.Widget(), self.admin, on_logout=lambda: None)
        self.assertIsInstance(frame.content.winfo_children()[0], smoke.gui["dashboard_frame"].DashboardFrame)
        frame.open_screen("tickets")
        self.assertIsInstance(frame.content.winfo_children()[0], smoke.gui["admin_tickets_frame"].AdminTicketsFrame)
        cashier_frame = gui_main.MainFrame(fake_tk.Widget(), self.cashier, on_logout=lambda: None)
        self.assertIsInstance(cashier_frame.content.winfo_children()[0], smoke.gui["cashier_home_frame"].CashierHomeFrame)
        cashier_frame.open_screen("tickets")        # старый раздел скрыт у кассира — игнорируется
        cashier_frame.open_screen("dashboard")      # админский пункт игнорируется
        self.assertIsInstance(cashier_frame.content.winfo_children()[0], smoke.gui["cashier_home_frame"].CashierHomeFrame)
        cashier_frame.open_screen("refund")
        self.assertIsInstance(cashier_frame.content.winfo_children()[0], smoke.gui["cashier_refund_frame"].CashierRefundFrame)

    def test_dashboard_shows_real_data_and_refreshes(self):
        frame = smoke.gui["dashboard_frame"].DashboardFrame(fake_tk.Widget(), self.admin)
        self.assertEqual(frame.cards["movies"].value_var.get(), "1")
        self.assertEqual(frame.cards["tickets"].value_var.get(), "0")
        self.sell(0)
        self.sell(1)
        frame.refresh()
        self.assertEqual(frame.cards["tickets"].value_var.get(), "2")
        self.assertIn("600", frame.cards["revenue"].value_var.get())
        self.assertEqual(len(frame.recent_table.tree.rows), 2)
        self.assertEqual(len(frame.upcoming_table.tree.rows), 1)
        frame._draw_chart()
        frame.destroy()
        self.assertIsNone(frame._job)

    def test_chart_geometry(self):
        boxes = smoke.gui["dashboard_frame"].bar_geometry([0, 50, 100], 400, 200)
        self.assertEqual(len(boxes), 3)
        heights = [b[3] - b[1] for b in boxes]
        self.assertEqual(heights[0], 2)                       # нулевой день виден тонкой линией
        self.assertAlmostEqual(heights[2], 2 * heights[1], places=5)
        self.assertTrue(all(0 <= b[0] < b[2] <= 400 for b in boxes))
        self.assertEqual(len(smoke.gui["dashboard_frame"].bar_geometry([], 10, 10)), 0)

    def test_admin_tickets_screen_search_details_refund(self):
        a, b = self.sell(0, client={"full_name": "Иван"}), self.sell(1, client={"full_name": "Мария"})
        frame = smoke.gui["admin_tickets_frame"].AdminTicketsFrame(fake_tk.Widget(), self.admin)
        self.assertEqual(set(frame.table.tree.rows), {str(a["id"]), str(b["id"])})
        frame.client_var.set("мар")
        frame.search()
        self.assertEqual(set(frame.table.tree.rows), {str(b["id"])})
        self.select(frame.table, b["id"])
        frame._on_select()
        self.assertIn("Мария", frame.details_var.get())
        self.assertIn("Куплен", frame.details_var.get())
        self.assertEqual(frame.refund_button.cget("state"), "normal")
        frame._refund()
        self.assertEqual(tickets.get_ticket(self.admin, b["id"])["status"], "returned")
        frame.client_var.set("")
        frame.id_var.set("zzz")
        frame.search()
        self.assertTrue(self.messages("warning"))
        self.assertEqual(self.messages("error"), [])

    def test_sessions_screen_filters_and_cancel(self):
        self.sell(0)
        frame = smoke.gui["sessions_frame"].SessionsFrame(fake_tk.Widget(), self.admin)
        self.assertEqual(len(frame.table.tree.rows), 1)
        other_hall = halls.create_hall(self.admin, "Зал 2", 1, 3)
        frame._load_filters()
        frame.hall_filter.set_value(other_hall)              # в другом зале сеансов нет
        frame.load()
        self.assertEqual(len(frame.table.tree.rows), 0)
        frame.hall_filter.set_value(self.hall_id)
        frame.movie_filter.set_value(self.movie_id)
        frame.load()
        self.assertEqual(len(frame.table.tree.rows), 1)
        self.select(frame.table, self.session_id)
        frame._cancel_session()
        self.assertIn("1 шт.", [m for k, _, m in fake_tk.MESSAGEBOX.calls if k == "confirm"][-1])
        self.assertEqual(self.count("sessions"), 1)          # сеанс остался в БД (история)
        self.assertEqual(len(frame.table.tree.rows), 0)      # но из списка пропал
        frame.cancelled_var.set(True)
        frame.load()
        self.assertEqual(list(frame.table.tree.rows.values())[0]["values"][-1], "Отменён")
        self.select(frame.table, self.session_id)
        frame._cancel_session()
        self.assertIn("уже отменён", self.messages("warning")[-1])

    def test_users_screen_search_edit_role(self):
        frame = smoke.gui["users_frame"].UsersFrame(fake_tk.Widget(), self.admin)
        self.assertEqual(len(frame.table.tree.rows), 3)
        frame.search_var.set("cash")
        frame.reload()
        self.assertEqual(len(frame.table.tree.rows), 1)
        uid = int(next(iter(frame.table.tree.rows)))
        self.select(frame.table, uid)
        frame._edit_user()
        self.submit(username="kassa2", full_name="Анна Новая")
        self.assertEqual(auth.login("kassa2", "secret1").full_name, "Анна Новая")
        frame.search_var.set("")
        frame.reload()
        self.select(frame.table, self.admin.id)
        frame._change_role()
        self.submit(role="cashier")
        self.assertEqual(auth.login("admin", "admin123").role, "admin")     # себя понизить нельзя
        self.assertIn("собственную", self.dialog().error_var.get())
        frame._create_cashier()
        self.submit(username="newkassa", password="secret1", full_name="Новый Кассир")
        self.assertEqual(auth.login("newkassa", "secret1").role, Role.CASHIER)

    def test_movies_screen_genre_pick_and_counts(self):
        genres_other = smoke.gui["movies_frame"].genre_service.create_genre(self.admin, "Комедия")
        frame = smoke.gui["movies_frame"].MoviesFrame(fake_tk.Widget(), self.admin)
        self.assertEqual(frame.genre_table.tree.rows[str(self.genre_id)]["values"], ("Драма", 1))
        self.assertEqual(frame.genre_table.tree.rows[str(genres_other)]["values"], ("Комедия", 0))
        self.select(frame.genre_table, genres_other)
        frame._on_genre_pick()
        self.assertEqual(len(frame.movie_table.tree.rows), 0)
        self.select(frame.genre_table, self.genre_id)
        frame._on_genre_pick()
        self.assertEqual(len(frame.movie_table.tree.rows), 1)
        frame._reset_filters()
        self.assertEqual(frame.count_var.get(), "Найдено: 1")

    def test_reports_screen_presets_and_cashier_report(self):
        self.sell(0)
        frame = smoke.gui["reports_frame"].ReportsFrame(fake_tk.Widget(), self.admin)
        frame.type_combo.set_value("cashiers")
        frame.set_period(7)
        self.assertEqual(frame.to_var.get(), "16.10.2026")
        self.assertEqual(frame.from_var.get(), "10.10.2026")
        self.assertEqual(frame._report["type"], "cashiers")
        self.assertEqual(len(frame.table.tree.rows), 2)      # сотрудник + «Итого»
        frame.set_month()
        self.assertEqual(frame.from_var.get(), "01.10.2026")
        import os
        path = os.path.join(self._tmp.name, "c.csv")
        fake_tk.FILEDIALOG.result = path
        frame.export()
        self.assertIn("Сотрудник", open(path, encoding="utf-8-sig").read())
        frame.type_combo.set_value("attendance")
        frame.generate()
        self.assertIn("by_hall", frame._report["tables"])


if __name__ == "__main__":
    unittest.main()
