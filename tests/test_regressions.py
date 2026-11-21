"""Регрессии аудита AVENOR: единое правило возврата, сценарии 1–6, миниатюры постеров.
Запуск:  python -m unittest tests.test_regressions -v"""
import os
import types
import unittest
from datetime import datetime
from unittest.mock import patch

from services import admin_service, buyer_service, cashier_service, hall_service as halls
from services import session_service as sessions
from services import ticket_service as tickets
from services.errors import PermissionDenied, ValidationError
from tests.base import CatalogTestCase

NOW = datetime(2026, 11, 17, 12, 0)
CARD = {"number": "4242 4242 4242 4242", "holder": "IVAN IVANOV", "expiry": "12/30", "cvc": "123"}


class AuditScenarios(CatalogTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("services.clock.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.hall_id = self.hall("Зал 1", 2, 5)
        scheme = halls.get_hall_scheme(self.admin, self.hall_id, self.db)
        self.seats = [s["id"] for row in scheme["rows"] for s in row["seats"]]

    def make_session(self, date="2026-11-18", time="19:00"):
        movie_id = self.movie("Сценарный фильм")
        return movie_id, sessions.create_session(self.admin, movie_id, self.hall_id, date, time, 300, self.db)

    def free(self, session_id, seat_id):
        seat_map = tickets.get_session_seat_map(self.cashier, session_id, self.db)
        return not next(s for r in seat_map["rows"] for s in r["seats"] if s["id"] == seat_id)["is_sold"]

    # СЦЕНАРИЙ 1: админ добавляет фильм и сеанс — они видны в афише покупателя
    def test_1_admin_adds_movie_and_session(self):
        movie_id, session_id = self.make_session()
        listed = sessions.list_sessions(self.admin, db_path=self.db)
        self.assertIn(session_id, [s["id"] for s in listed])
        self.assertIn(movie_id, [m["id"] for m in buyer_service.catalog(self.viewer, db_path=self.db)])

    # СЦЕНАРИИ 2-5: покупка -> поиск кассиром -> возврат админом -> повторная продажа места
    def test_2_to_5_full_cycle(self):
        _, session_id = self.make_session()
        order = buyer_service.place_order(self.viewer, session_id, [self.seats[0]], CARD, self.db)
        ticket_id = order["tickets"][0]["id"]
        self.assertFalse(self.free(session_id, self.seats[0]))
        with self.assertRaises(ValidationError):                      # занятое место второй раз не продаётся
            buyer_service.place_order(self.viewer, session_id, [self.seats[0]], CARD, self.db)
        found = cashier_service.search_tickets(self.cashier, ticket_id=ticket_id, db_path=self.db)
        self.assertEqual([t["id"] for t in found], [ticket_id])
        found_admin = admin_service.search_tickets(self.admin, ticket_id=ticket_id, db_path=self.db)
        self.assertEqual([t["id"] for t in found_admin], [ticket_id])
        self.assertTrue(found_admin[0]["is_refundable"])
        self.assertEqual(found_admin[0]["refund_reason"], "")
        refunded = tickets.refund_ticket(self.admin, ticket_id, self.db)
        self.assertEqual(refunded["status"], "returned")
        self.assertTrue(self.free(session_id, self.seats[0]))          # место снова свободно
        again = buyer_service.place_order(self.viewer, session_id, [self.seats[0]], CARD, self.db)
        self.assertNotEqual(again["tickets"][0]["id"], ticket_id)      # новый уникальный номер

    # СЦЕНАРИЙ 6: чужие билеты и запрещённые разделы
    def test_6_access_control(self):
        _, session_id = self.make_session()
        other = tickets.sell_ticket(self.cashier, session_id, self.seats[1], {"full_name": "Чужой Клиент"}, self.db)
        with self.assertRaises(PermissionDenied):
            tickets.get_ticket(self.viewer, other["id"], self.db)
        with self.assertRaises(PermissionDenied):
            buyer_service.refund(self.viewer, other["id"], self.db)
        with self.assertRaises(PermissionDenied):
            admin_service.search_tickets(self.viewer, db_path=self.db)
        with self.assertRaises(PermissionDenied):
            cashier_service.search_tickets(self.viewer, db_path=self.db)

    # Корень жалобы «не могу оформить возврат»: сеанс уже начался -> единая причина во всех слоях
    def test_refund_rule_is_single_source_for_all_roles(self):
        _, session_id = self.make_session(date="2026-11-17", time="18:00")   # начнётся позже «сейчас» (12:00)
        sold = tickets.sell_ticket(self.cashier, session_id, self.seats[0], {"full_name": "Иван"}, self.db)
        later = datetime(2026, 11, 17, 18, 30)
        with patch("services.clock.now", return_value=later):
            row = admin_service.search_tickets(self.admin, ticket_id=sold["id"], db_path=self.db)[0]
            self.assertFalse(row["is_refundable"])
            self.assertEqual(row["refund_reason"], tickets.REASON_SESSION_STARTED)
            with self.assertRaises(ValidationError) as ctx:
                tickets.refund_ticket(self.admin, sold["id"], self.db)
            self.assertEqual(str(ctx.exception), row["refund_reason"])    # сервис и экран говорят одно и то же
            cashier_service.open_shift(self.cashier, self.db)
            check = cashier_service.refund_check(self.cashier, sold["id"], self.db)
            self.assertEqual((check["can_refund"], check["reason"]), (False, row["refund_reason"]))

    def test_refund_block_reason_values(self):
        self.assertEqual(tickets.refund_block_reason("sold", False), "")
        self.assertEqual(tickets.refund_block_reason("sold", True), tickets.REASON_SESSION_STARTED)
        self.assertEqual(tickets.refund_block_reason("returned", False), tickets.REASON_ALREADY_RETURNED)

    def test_refund_of_cancelled_session_ticket_is_consistent(self):
        _, session_id = self.make_session()
        sold = tickets.sell_ticket(self.cashier, session_id, self.seats[0], {"full_name": "Иван"}, self.db)
        admin_service.cancel_session(self.admin, session_id, self.db)
        row = admin_service.search_tickets(self.admin, ticket_id=sold["id"], db_path=self.db)[0]
        self.assertEqual(row["status"], "returned")
        self.assertFalse(row["is_refundable"])
        with self.assertRaises(ValidationError):
            tickets.refund_ticket(self.admin, sold["id"], self.db)


class FakeImageTkPhoto:
    """Как ImageTk.PhotoImage из Pillow: метода subsample НЕТ."""


class PosterThumbTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import test_gui_smoke as smoke
        smoke.setUpModule()
        cls.smoke, cls.gui = smoke, smoke.gui

    @classmethod
    def tearDownClass(cls):
        cls.smoke.tearDownModule()

    def test_thumb_with_pillow_object_has_no_subsample_call(self):
        theme, neon = self.gui["theme"], self.gui["neon"]
        theme._posters.clear()
        real = os.path.join(os.path.dirname(__file__), "regress_poster.png")
        open(real, "wb").close()
        self.addCleanup(os.remove, real)
        photo = FakeImageTkPhoto()
        with patch.object(theme, "_pillow_poster", return_value=photo) as pillow:
            self.assertIs(neon.poster_thumb(real, 1), photo)      # раньше здесь падало AttributeError: subsample
            half = tuple(v // 2 for v in theme.spec.POSTER_SIZES["small"])
            self.assertEqual(pillow.call_args.args[1:], half)
        theme._posters.clear()

    def test_thumb_placeholder_when_no_poster(self):
        neon = self.gui["neon"]
        self.assertIsNotNone(neon.poster_thumb(None, 4))


if __name__ == "__main__":
    unittest.main()


class CashierShiftVerdict(CatalogTestCase):
    def test_refund_verdict_matches_shift_requirement(self):
        with patch("services.clock.now", return_value=NOW):
            hall_id = self.hall("Зал 1", 1, 3)
            seat = halls.get_hall_scheme(self.admin, hall_id, self.db)["rows"][0]["seats"][0]["id"]
            session_id = sessions.create_session(self.admin, self.movie("Ф"), hall_id, "2026-11-18", "19:00", 300, self.db)
            sold = tickets.sell_ticket(self.cashier, session_id, seat, {"full_name": "Иван"}, self.db)
            check = cashier_service.refund_check(self.cashier, sold["id"], self.db)
            self.assertFalse(check["can_refund"])                       # смена закрыта: экран не обещает возврат
            with self.assertRaises(ValidationError):
                cashier_service.refund(self.cashier, sold["id"], self.db)
            cashier_service.open_shift(self.cashier, self.db)
            self.assertTrue(cashier_service.refund_check(self.cashier, sold["id"], self.db)["can_refund"])
            self.assertEqual(cashier_service.refund(self.cashier, sold["id"], self.db)["status"], "returned")


class InputFormattingTests(unittest.TestCase):
    def setUp(self):
        from gui import formatting as f   # чистые функции: tkinter не нужен
        self.f = f

    def test_card_number_groups_by_four(self):
        self.assertEqual(self.f.format_card_number("4242424242424242"), "4242 4242 4242 4242")
        self.assertEqual(self.f.format_card_number("42a42-4"), "4242 4")
        self.assertEqual(self.f.format_card_number("4242 4242 4242 4242 99"), "4242 4242 4242 4242")

    def test_expiry_gets_slash(self):
        self.assertEqual(self.f.format_expiry("1228"), "12/28")
        self.assertEqual(self.f.format_expiry("12"), "12")
        self.assertEqual(self.f.format_expiry("122"), "12/2")
        self.assertEqual(self.f.format_expiry("1"), "1")
        self.assertEqual(self.f.format_expiry("5"), "05")
        self.assertEqual(self.f.format_expiry("12/28"), "12/28")

    def test_holder_cvc_phone(self):
        self.assertEqual(self.f.format_holder("marina  norvardyan"), "MARINA NORVARDYAN")
        self.assertEqual(self.f.format_holder("Марина"), "")
        self.assertEqual(self.f.format_cvc("12a34"), "123")
        self.assertEqual(self.f.format_phone_input("89169035600"), "+7 916 903-56-00")
        self.assertEqual(self.f.format_phone_input("+7 916"), "+7 916")

    def test_formatted_values_pass_service_validation(self):
        buyer_service.validate_card(self.f.format_card_number("4242424242424242"), self.f.format_holder("marina"),
                                    self.f.format_expiry("1230"), self.f.format_cvc("123"))
        from services.validators import normalize_phone
        self.assertTrue(normalize_phone(self.f.format_phone_input("89169035600")))


class AdminCannotSell(CatalogTestCase):
    def test_admin_has_no_sell_permission_and_no_afisha_menu(self):
        from gui.navigation import menu_for
        from services.permissions import Permission
        self.assertFalse(self.admin.has_permission(Permission.SELL_TICKET))
        self.assertTrue(self.admin.has_permission(Permission.REFUND_TICKET))
        self.assertNotIn("schedule", [m.key for m in menu_for(self.admin)])
