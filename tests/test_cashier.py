"""Рабочее место кассира: сервисы (смена, продажа, возврат, история, права) и экраны на заглушке tkinter.

Запуск:  python -m unittest tests.test_cashier -v
"""
import sqlite3
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import fake_tk
from tests import test_gui_screens as screens
from tests import test_gui_smoke as smoke


def setUpModule():
    smoke.setUpModule()


def tearDownModule():
    smoke.tearDownModule()


from database.connection import get_connection             # noqa: E402
from services import auth_service as auth                  # noqa: E402
from services import cashier_service as cs                 # noqa: E402
from services import movie_service as movies               # noqa: E402
from services import report_service as reports             # noqa: E402
from services import ticket_print                          # noqa: E402
from services import ticket_service as tickets             # noqa: E402
from services.errors import PermissionDenied, ValidationError   # noqa: E402
from services.permissions import Role                      # noqa: E402

gui = smoke.gui


class CashierBase(screens.ScreenBase):
    def setUp(self):
        super().setUp()
        auth.create_user_account(self.admin, "cash2", "secret1", Role.CASHIER, "Кассир Борис")
        self.cashier2 = auth.login("cash2", "secret1")

    def sell_cs(self, seats=(0,), method="cash", actor=None, **kw):
        return cs.sell(actor or self.cashier, self.session_id, [self.seat_ids[i] for i in seats], method, **kw)

    def rows(self, sql, *params):
        conn = get_connection(self.db)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()


class CashierServiceTests(CashierBase):
    def test_permissions(self):
        for actor in (self.viewer, self.admin):
            for call in (lambda a: cs.open_shift(a), lambda a: cs.current_shift(a), lambda a: cs.list_my_sales(a),
                         lambda a: cs.dashboard(a), lambda a: cs.sell(a, self.session_id, [self.seat_ids[0]], "cash")):
                with self.assertRaises(PermissionDenied):
                    call(actor)

    def test_shift_lifecycle(self):
        self.assertIsNone(cs.current_shift(self.cashier))
        shift = cs.open_shift(self.cashier)
        self.assertEqual(cs.current_shift(self.cashier)["id"], shift["id"])
        with self.assertRaises(ValidationError):
            cs.open_shift(self.cashier)                      # вторая активная смена недопустима
        cs.open_shift(self.cashier2)                         # у другого кассира своя смена
        self.sell_cs((0, 1), "card")
        self.sell_cs((2,), "cash")
        summary = cs.close_shift(self.cashier)
        self.assertEqual((summary["sales_count"], summary["tickets_sold"], summary["sales_amount"]), (2, 3, 900))
        self.assertIsNone(cs.current_shift(self.cashier))
        self.assertIn("900", cs.shift_report_text(summary, "Кассир Анна").replace(" ", "").replace("\xa0", ""))
        with self.assertRaises(ValidationError):
            cs.close_shift(self.cashier)
        self.assertEqual(len(cs.list_my_shifts(self.cashier)), 1)
        self.assertEqual(cs.list_my_shifts(self.cashier2)[0]["shift"]["closed_at"], None)

    def test_sale_requires_open_shift(self):
        with self.assertRaises(ValidationError):
            self.sell_cs()
        self.assertEqual(self.count("tickets"), 0)

    def test_sale_saves_sale_and_tickets_together(self):
        cs.open_shift(self.cashier)
        result = self.sell_cs((0, 1), "card")
        self.assertEqual(result["total"], 600)
        sale = self.rows("SELECT * FROM sales")[0]
        self.assertEqual((sale["cashier_id"], sale["payment_method"], sale["total"]), (self.cashier.id, "card", 600))
        self.assertEqual([r["sale_id"] for r in self.rows("SELECT sale_id FROM tickets")], [sale["id"]] * 2)
        self.assertEqual({r["seller_id"] for r in self.rows("SELECT seller_id FROM tickets")}, {self.cashier.id})

    def test_failed_sale_leaves_nothing(self):
        cs.open_shift(self.cashier)
        self.sell_cs((0,))
        with self.assertRaises(Exception):
            self.sell_cs((1, 0))                             # место 0 уже продано -> вся продажа отклоняется
        self.assertEqual((self.count("sales"), self.count("tickets")), (1, 1))
        with self.assertRaises(ValidationError):
            self.sell_cs((1,), "bitcoin")
        self.assertEqual((self.count("sales"), self.count("tickets")), (1, 1))

    def test_quote_marks_unavailable_and_totals(self):
        cs.open_shift(self.cashier)
        self.sell_cs((0,))
        q = cs.quote(self.cashier, self.session_id, [self.seat_ids[0], self.seat_ids[1], self.seat_ids[2]])
        self.assertEqual((q["count"], q["total"], q["unavailable"]), (2, 600, [self.seat_ids[0]]))

    def test_refund_rules(self):
        cs.open_shift(self.cashier)
        tid = self.sell_cs()["tickets"][0]["id"]
        self.assertTrue(cs.refund_check(self.cashier, tid)["can_refund"])
        cs.refund(self.cashier, tid)
        check = cs.refund_check(self.cashier, tid)
        self.assertFalse(check["can_refund"])
        with self.assertRaises(ValidationError):
            cs.refund(self.cashier, tid)                      # повторный возврат
        row = self.rows("SELECT * FROM tickets WHERE id = ?", tid)[0]
        self.assertEqual((row["status"], row["refunded_by"]), ("returned", self.cashier.id))
        self.assertEqual(self.count("sales"), 1)              # запись о продаже сохранена
        self.sell_cs()                                        # место снова свободно
        cs.close_shift(self.cashier)
        with self.assertRaises(ValidationError):
            cs.refund(self.cashier, self.sell_tid_after_reopen())

    def sell_tid_after_reopen(self):
        cs.open_shift(self.cashier)
        tid = self.sell_cs((3,))["tickets"][0]["id"]
        cs.close_shift(self.cashier)
        return tid

    def test_started_session_cannot_be_refunded(self):
        cs.open_shift(self.cashier)
        tid = self.sell_cs()["tickets"][0]["id"]
        with patch("services.clock.now", return_value=datetime(2026, 10, 17, 19, 0)):
            self.assertFalse(cs.refund_check(self.cashier, tid)["can_refund"])
            with self.assertRaises(ValidationError):
                cs.refund(self.cashier, tid)

    def test_history_is_own_only_with_filters(self):
        cs.open_shift(self.cashier)
        cs.open_shift(self.cashier2)
        mine = self.sell_cs((0, 1))["sale_id"]
        other = self.sell_cs((2,), actor=self.cashier2)["sale_id"]
        ids = [s["id"] for s in cs.list_my_sales(self.cashier)]
        self.assertEqual(ids, [mine])
        self.assertEqual(cs.list_my_sales(self.cashier, sale_id=other), [])
        with self.assertRaises(Exception):
            cs.get_sale_tickets(self.cashier, other)
        self.assertEqual(len(cs.get_sale_tickets(self.cashier, mine)), 2)
        cs.refund(self.cashier, cs.get_sale_tickets(self.cashier, mine)[0]["id"])
        self.assertEqual(cs.list_my_sales(self.cashier)[0]["status"], "partial")
        self.assertEqual(len(cs.list_my_sales(self.cashier, status="partial")), 1)
        self.assertEqual(cs.list_my_sales(self.cashier, status="returned"), [])
        self.assertEqual(cs.list_my_sales(self.cashier, movie_id=self.movie_id + 99), [])
        self.assertEqual(cs.list_my_sales(self.cashier, date_from="2026-10-16", date_to="2026-10-16")[0]["id"], mine)
        s = cs.shift_summary(self.cashier)
        self.assertEqual((s["tickets_sold"], s["returns_count"], s["net_amount"]), (2, 1, 300))

    def test_search_by_movie_and_buyer(self):
        cs.open_shift(self.cashier)
        self.sell_cs(client={"full_name": "Иванов Пётр"})
        self.assertEqual(len(cs.search_tickets(self.cashier, movie="дюн")), 1)
        self.assertEqual(len(cs.search_tickets(self.cashier, movie="нет такого")), 0)
        self.assertEqual(len(cs.search_tickets(self.cashier, client="Иванов")), 1)
        self.assertEqual(len(cs.search_tickets(self.cashier, session_id=self.session_id, status="sold")), 1)
        self.assertEqual(len(cs.search_tickets(self.cashier, date="17.10.2026")), 1)

    def test_buyer_and_admin_sale_paths_unchanged(self):
        with self.assertRaises(PermissionDenied):                  # администратор не продаёт
            tickets.sell_ticket(self.admin, self.session_id, self.seat_ids[4], {"full_name": "Админ-клиент"})
        t = tickets.sell_ticket(self.cashier, self.session_id, self.seat_ids[4], {"full_name": "Клиент"})
        self.assertEqual(self.rows("SELECT sale_id FROM tickets WHERE id = ?", t["id"])[0]["sale_id"], None)
        self.assertEqual(self.count("sales"), 0)

    def test_cashier_cannot_manage_other_areas(self):
        with self.assertRaises(PermissionDenied):
            movies.create_movie(self.cashier, "X", self.genre_id, 100, "12+")
        with self.assertRaises(PermissionDenied):
            reports.cashier_report(self.cashier, "2026-10-01", "2026-10-31")
        with self.assertRaises(PermissionDenied):
            auth.create_user_account(self.cashier, "zzz", "secret1", Role.VIEWER, "Z")

    def test_ticket_print(self):
        cs.open_shift(self.cashier)
        t = self.sell_cs()["tickets"][0]
        code = ticket_print.ticket_code(t)
        self.assertEqual(code, ticket_print.ticket_code(t))
        self.assertTrue(code.startswith(f"AVN-{t['id']:06d}-"))
        html = ticket_print.tickets_html([t])
        for part in ("AVENOR", "Дюна", code):
            self.assertIn(part, html)
        with self.assertRaises(ValidationError):
            ticket_print.tickets_html([])

    def test_legacy_sales_are_backfilled(self):
        from database import schema
        cs.open_shift(self.cashier)
        tid = self.sell_cs()["tickets"][0]["id"]
        conn = get_connection(self.db)
        conn.execute("UPDATE tickets SET sale_id = NULL WHERE id = ?", (tid,))
        conn.execute("DELETE FROM sales")
        conn.commit()
        schema._backfill_sales(conn)
        conn.commit()
        sale = conn.execute("SELECT s.* FROM sales s JOIN tickets t ON t.sale_id = s.id WHERE t.id = ?", (tid,)).fetchone()
        conn.close()
        self.assertEqual(sale["cashier_id"], self.cashier.id)
        self.assertEqual(sale["payment_method"], None)


class CashierScreenTests(CashierBase):
    def seat(self, frame, index):
        return next(s for r in frame._seat_data["rows"] for s in r["seats"] if s["id"] == self.seat_ids[index])

    def test_home_shows_real_numbers(self):
        cs.open_shift(self.cashier)
        self.sell_cs((0, 1))
        frame = gui["cashier_home_frame"].CashierHomeFrame(fake_tk.Widget(), self.cashier)
        self.assertEqual(frame.cards["tickets"].value_var.get(), "2")
        frame.destroy()

    def test_sale_flow_end_to_end(self):
        cs.open_shift(self.cashier)
        frame = gui["cashier_sale_frame"].CashierSaleFrame(fake_tk.Widget(), self.cashier)
        frame._load_movie(self.movie_id)
        frame._open_session(self.session_id, False)
        frame._on_seat_click(self.seat(frame, 0))
        frame._on_seat_click(self.seat(frame, 1))
        self.assertEqual(len(frame._selected), 2)
        frame._to_payment()
        dialog = self.last(gui["cashier_dialogs"].PaymentDialog)
        dialog.method_combo.set_value("card")
        dialog.confirm()
        self.assertEqual((self.count("sales"), self.count("tickets")), (1, 2))
        self.assertTrue(any(isinstance(w, gui["cashier_dialogs"].TicketDialog) for w in fake_tk.CREATED))
        frame.destroy()

    def test_sale_detects_seat_sold_elsewhere(self):
        cs.open_shift(self.cashier)
        cs.open_shift(self.cashier2)
        frame = gui["cashier_sale_frame"].CashierSaleFrame(fake_tk.Widget(), self.cashier)
        frame._load_movie(self.movie_id)
        frame._open_session(self.session_id, False)
        frame._on_seat_click(self.seat(frame, 0))
        self.sell_cs((0,), actor=self.cashier2)               # другое рабочее место успело раньше
        frame._to_payment()
        self.assertEqual(self.count("tickets"), 1)
        self.assertTrue(self.messages("warning") or self.messages("showwarning") or fake_tk.MESSAGEBOX.calls)
        frame.destroy()

    def test_search_refund_history_shift_screens(self):
        cs.open_shift(self.cashier)
        sale = self.sell_cs((0, 1), client={"full_name": "Сидоров"})
        tid = sale["tickets"][0]["id"]
        search = gui["cashier_search_frame"].CashierSearchFrame(fake_tk.Widget(), self.cashier)
        search.vars["client"].set("Сидоров")
        search.search()
        self.assertEqual(len(search._tickets), 2)
        refund = gui["cashier_refund_frame"].CashierRefundFrame(fake_tk.Widget(), self.cashier)
        refund.load_ticket(tid)
        self.assertTrue(refund._ticket and "возможен" in refund.verdict_var.get())
        with patch.object(gui["cashier_refund_frame"], "ask_confirm", return_value=True):
            refund.refund()
        self.assertEqual(self.rows("SELECT status FROM tickets WHERE id = ?", tid)[0]["status"], "returned")
        refund.find()
        self.assertIn("уже возвращён", refund.verdict_var.get())
        history = gui["cashier_history_frame"].CashierHistoryFrame(fake_tk.Widget(), self.cashier)
        self.assertEqual(list(history._sales), [sale["sale_id"]])
        shift = gui["cashier_shift_frame"].CashierShiftFrame(fake_tk.Widget(), self.cashier)
        self.assertEqual(shift.open_button.cget("state") if hasattr(shift.open_button, "cget") else "disabled", "disabled")
        with patch.object(gui["cashier_shift_frame"], "ask_confirm", return_value=True):
            shift.close_shift()
        self.assertIsNone(cs.current_shift(self.cashier))
        self.assertTrue(any(isinstance(w, gui["cashier_dialogs"].TextReportDialog) for w in fake_tk.CREATED))

    def test_navigate_from_search_to_refund(self):
        cs.open_shift(self.cashier)
        tid = self.sell_cs()["tickets"][0]["id"]
        main = gui["main_frame"].MainFrame(fake_tk.Widget(), self.cashier, on_logout=lambda: None)
        main.open_screen("refund", ticket_id=tid)
        frame = main.content.winfo_children()[0]
        self.assertEqual(frame.id_var.get(), str(tid))
        self.assertIsNotNone(frame._ticket)


if __name__ == "__main__":
    unittest.main()
