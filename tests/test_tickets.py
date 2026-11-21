"""Проверка продажи и возврата билетов. Запуск:  python -m unittest tests.test_tickets -v"""
import threading
import unittest
from datetime import datetime
from unittest.mock import patch

from database import crud
from database.connection import get_connection
from services import client_service as clients
from services import hall_service as halls
from services import session_service as sessions
from services import ticket_service as tickets
from services.errors import PermissionDenied, ValidationError
from tests.base import CatalogTestCase

FAKE_NOW = datetime(2026, 10, 16, 12, 0)
_DEFAULT_CLIENT = object()   # отличаем «не передали» от осознанного None / ""


class TicketTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("services.clock.now", return_value=FAKE_NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.hall_id = self.hall("Зал 1", 2, 5)    # 10 мест
        self.other_hall = self.hall("Зал 2", 1, 2)
        self.movie_id = self.movie("Фильм", duration=100)
        self.session_id = sessions.create_session(
            self.admin, self.movie_id, self.hall_id, "2026-11-01", "18:00", 300, self.db)
        scheme = halls.get_hall_scheme(self.admin, self.hall_id, self.db)
        self.seat_ids = [s["id"] for row in scheme["rows"] for s in row["seats"]]

    def sell(self, seat_index=0, client=_DEFAULT_CLIENT, actor=None, session_id=None):
        if client is _DEFAULT_CLIENT:
            client = {"full_name": "Иван Иванов"}
        return tickets.sell_ticket(actor or self.cashier, session_id or self.session_id,
                                   self.seat_ids[seat_index], client, self.db)

    def count(self, table):
        conn = get_connection(self.db)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    # --- продажа
    def test_sell_returns_receipt_and_marks_seat(self):
        t = self.sell(0, {"full_name": " Иван  Иванов ", "email": "IVAN@Mail.ru"})
        self.assertEqual((t["status"], t["price"], t["client_name"]), ("sold", 300.0, "Иван Иванов"))
        self.assertEqual((t["movie_title"], t["hall_name"], t["seat_label"]),
                         ("Фильм", "Зал 1", "ряд 1, место 1"))
        self.assertEqual(t["client_email"], "ivan@mail.ru")
        self.assertEqual(t["purchase_date"], "2026-10-16 12:00:00")
        self.assertTrue(t["is_refundable"])

        seat_map = tickets.get_session_seat_map(self.cashier, self.session_id, self.db)
        first = seat_map["rows"][0]["seats"][0]
        self.assertTrue(first["is_sold"])
        self.assertEqual(first["ticket_id"], t["id"])
        self.assertFalse(seat_map["rows"][0]["seats"][1]["is_sold"])
        self.assertEqual(seat_map["session"]["seats_free"], 9)
        self.assertTrue(seat_map["is_open_for_sale"])

    def test_double_sale_rejected(self):
        self.sell(0)
        with self.assertRaises(ValidationError) as ctx:
            self.sell(0, {"full_name": "Другой Клиент"})
        self.assertIn("занято", str(ctx.exception))
        self.assertEqual(self.count("tickets"), 1)

    def test_failed_sale_leaves_no_stray_client(self):
        self.sell(0)
        before = self.count("clients")
        with self.assertRaises(ValidationError):
            self.sell(0, {"full_name": "Новый Человек", "phone": "89990001122"})
        self.assertEqual(self.count("clients"), before)

    def test_resale_after_refund(self):
        t = self.sell(0)
        tickets.refund_ticket(self.cashier, t["id"], self.db)
        self.sell(0, {"full_name": "Следующий"})
        self.assertEqual(self.count("tickets"), 2)

    def test_wrong_seat_or_session(self):
        foreign = crud.list_seats_by_hall(get_connection(self.db), self.other_hall)[0]["id"]
        with self.assertRaises(ValidationError):
            tickets.sell_ticket(self.cashier, self.session_id, foreign, {"full_name": "А"}, self.db)
        with self.assertRaises(ValidationError):
            tickets.sell_ticket(self.cashier, 9999, self.seat_ids[0], {"full_name": "А"}, self.db)
        with self.assertRaises(ValidationError):
            tickets.sell_ticket(self.cashier, self.session_id, 99999, {"full_name": "А"}, self.db)
        for bad in ("abc", None, 0, True):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                tickets.sell_ticket(self.cashier, self.session_id, bad, {"full_name": "А"}, self.db)

    # --- начало сеанса
    def test_sales_and_refunds_closed_after_start(self):
        t = self.sell(0)
        with patch("services.clock.now", return_value=datetime(2026, 11, 1, 17, 59)):
            self.sell(1)                                         # за минуту до начала — можно
        with patch("services.clock.now", return_value=datetime(2026, 11, 1, 18, 0)):
            with self.assertRaises(ValidationError) as ctx:
                self.sell(2)
            self.assertIn("начался", str(ctx.exception))
            with self.assertRaises(ValidationError) as ctx:
                tickets.refund_ticket(self.cashier, t["id"], self.db)
            self.assertIn("начался", str(ctx.exception))
            seat_map = tickets.get_session_seat_map(self.cashier, self.session_id, self.db)
            self.assertFalse(seat_map["is_open_for_sale"])
            self.assertFalse(tickets.get_ticket(self.cashier, t["id"], self.db)["is_refundable"])

    # --- клиенты
    def test_client_reused_by_phone_and_normalized(self):
        a = self.sell(0, {"full_name": "Пётр", "phone": "8 (999) 123-45-67"})
        b = self.sell(1, {"full_name": "Пётр П.", "phone": "+7 999 123 45 67"})
        self.assertEqual(a["client_phone"], "+79991234567")
        self.assertEqual(a["client_id"], b["client_id"])
        c = self.sell(2, {"full_name": "Другое имя", "email": "x@y.ru"})
        d = self.sell(3, {"full_name": "Тот же email", "email": "X@Y.ru"})
        self.assertEqual(c["client_id"], d["client_id"])

    def test_existing_client_by_id(self):
        cid = self.sell(0)["client_id"]
        self.assertEqual(self.sell(1, cid)["client_id"], cid)
        with self.assertRaises(ValidationError):
            self.sell(2, 99999)

    def test_invalid_client_data(self):
        bad = [None, "", {"full_name": ""}, {"full_name": "А", "phone": "123"},
               {"full_name": "А", "phone": "abc"}, {"full_name": "А", "email": "no-at"},
               {"full_name": "х" * 101}]
        for client in bad:
            with self.assertRaises(ValidationError, msg=repr(client)):
                self.sell(0, client)
        self.assertEqual(self.count("tickets"), 0)

    def test_search_clients(self):
        self.sell(0, {"full_name": "Мария Сидорова", "phone": "+79990001122"})
        self.assertEqual(len(clients.search_clients(self.cashier, "СИДОР", db_path=self.db)), 1)
        self.assertEqual(len(clients.search_clients(self.cashier, "0001122", db_path=self.db)), 1)
        self.assertEqual(len(clients.search_clients(self.cashier, "нет такого", db_path=self.db)), 0)

    # --- несколько мест за одну покупку
    def test_sell_several_seats_in_one_purchase(self):
        ids = [self.seat_ids[0], self.seat_ids[1], self.seat_ids[1]]   # дубликат места
        result = tickets.sell_tickets(self.cashier, self.session_id, ids, {"full_name": "Группа"}, self.db)
        self.assertEqual(len(result), 2)
        self.assertEqual(len({t["client_id"] for t in result}), 1)
        self.assertEqual(self.count("tickets"), 2)

    def test_multi_sale_is_all_or_nothing(self):
        self.sell(0)
        clients_before = self.count("clients")
        with self.assertRaises(ValidationError):   # второе место свободно, первое занято
            tickets.sell_tickets(self.cashier, self.session_id, [self.seat_ids[1], self.seat_ids[0]],
                                 {"full_name": "Новый"}, self.db)
        self.assertEqual(self.count("tickets"), 1)
        self.assertEqual(self.count("clients"), clients_before)

    def test_multi_sale_input_limits(self):
        too_many = self.seat_ids[:tickets.MAX_SEATS_PER_PURCHASE] + [999999]
        for bad in ([], "12", None, too_many):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                tickets.sell_tickets(self.cashier, self.session_id, bad, {"full_name": "А"}, self.db)
        self.assertEqual(self.count("tickets"), 0)

    # --- возврат
    def test_refund_flow(self):
        t = self.sell(0)
        self.assertIsNone(t["returned_at"])
        r = tickets.refund_ticket(self.cashier, t["id"], self.db)
        self.assertEqual((r["status"], r["is_refundable"]), ("returned", False))
        self.assertEqual(r["returned_at"], "2026-10-16 12:00:00")
        seat_map = tickets.get_session_seat_map(self.cashier, self.session_id, self.db)
        self.assertFalse(seat_map["rows"][0]["seats"][0]["is_sold"])
        with self.assertRaises(ValidationError):
            tickets.refund_ticket(self.cashier, t["id"], self.db)      # повторный возврат
        with self.assertRaises(ValidationError):
            tickets.refund_ticket(self.cashier, 9999, self.db)

    # --- пользователь покупает сам
    def test_viewer_buys_only_for_himself(self):
        schemes = tickets.get_session_seat_map(self.viewer, self.session_id, self.db)   # схема зала ему доступна
        self.assertEqual(len(schemes["rows"]), 2)
        stranger = {"full_name": "Чужой Человек"}                                       # чужие данные игнорируются
        t = self.sell(0, stranger, actor=self.viewer)
        self.assertEqual(t["client_id"], self.viewer.client_id)
        two = tickets.sell_tickets(self.viewer, self.session_id, self.seat_ids[1:3], None, self.db)
        self.assertEqual({x["client_id"] for x in two}, {self.viewer.client_id})
        self.assertEqual(len(tickets.list_my_tickets(self.viewer, self.db)), 3)
        with self.assertRaises(ValidationError):                                         # занятое место по-прежнему нельзя
            self.sell(0, actor=self.viewer)
        with self.assertRaises(PermissionDenied):                                        # возврат и поиск — только у кассы
            tickets.refund_ticket(self.viewer, t["id"], self.db)
        with self.assertRaises(PermissionDenied):
            tickets.search_tickets(self.viewer, db_path=self.db)

    def test_viewer_without_client_card_cannot_buy(self):
        from dataclasses import replace
        orphan = replace(self.viewer, client_id=None)
        with self.assertRaises(ValidationError):
            self.sell(0, actor=orphan)

    # --- права
    def test_permissions(self):
        t = self.sell(0)
        with self.assertRaises(PermissionDenied):
            tickets.refund_ticket(self.viewer, t["id"], self.db)
        with self.assertRaises(PermissionDenied):
            tickets.search_tickets(self.viewer, db_path=self.db)
        with self.assertRaises(PermissionDenied):
            clients.search_clients(self.viewer, "", db_path=self.db)

    # --- поиск
    def test_search_by_all_criteria(self):
        t1 = self.sell(0, {"full_name": "Иван Иванов", "phone": "89991234567"})
        t2 = self.sell(1, {"full_name": "Анна Петрова", "email": "anna@mail.ru"})
        tickets.refund_ticket(self.cashier, t2["id"], self.db)

        def ids(**kw):
            return {t["id"] for t in tickets.search_tickets(self.cashier, db_path=self.db, **kw)}

        self.assertEqual(ids(), {t1["id"], t2["id"]})
        self.assertEqual(ids(ticket_id=t1["id"]), {t1["id"]})
        self.assertEqual(ids(client="ИВАНОВ"), {t1["id"]})
        self.assertEqual(ids(client="123-45-67"), {t1["id"]})
        self.assertEqual(ids(client="anna@"), {t2["id"]})
        self.assertEqual(ids(session_id=self.session_id), {t1["id"], t2["id"]})
        self.assertEqual(ids(date="01.11.2026"), {t1["id"], t2["id"]})
        self.assertEqual(ids(date="2026-11-02"), set())
        self.assertEqual(ids(status="returned"), {t2["id"]})
        self.assertEqual(ids(status="sold", client="Иван"), {t1["id"]})
        self.assertEqual(ids(ticket_id="", client="", status=""), {t1["id"], t2["id"]})  # пустые поля формы
        with self.assertRaises(ValidationError):
            tickets.search_tickets(self.cashier, status="paid", db_path=self.db)
        with self.assertRaises(ValidationError):
            tickets.search_tickets(self.cashier, ticket_id="abc", db_path=self.db)

    # --- билеты пользователя
    def test_viewer_sees_only_own_tickets(self):
        mine = self.sell(0, self.viewer.client_id)
        other = self.sell(1, {"full_name": "Чужой Клиент"})
        listed = tickets.list_my_tickets(self.viewer, self.db)
        self.assertEqual([t["id"] for t in listed], [mine["id"]])
        self.assertEqual(tickets.get_ticket(self.viewer, mine["id"], self.db)["id"], mine["id"])
        with self.assertRaises(PermissionDenied):
            tickets.get_ticket(self.viewer, other["id"], self.db)
        self.assertEqual(tickets.get_ticket(self.cashier, other["id"], self.db)["id"], other["id"])
        self.assertEqual(tickets.list_my_tickets(self.admin, self.db), [])   # у админа нет клиентской карточки

    # --- гонка
    def test_concurrent_sales_of_same_seat_only_one_succeeds(self):
        workers, barrier, outcomes, lock = 8, threading.Barrier(8), [], threading.Lock()

        def worker(i):
            barrier.wait()   # все стартуют одновременно
            try:
                tickets.sell_ticket(self.cashier, self.session_id, self.seat_ids[0],
                                    {"full_name": f"Клиент {i}"}, self.db)
                result = "ok"
            except ValidationError:
                result = "busy"
            except Exception as exc:   # любая другая ошибка = провал теста
                result = repr(exc)
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(outcomes.count("busy"), workers - 1, outcomes)
        self.assertEqual(self.count("tickets"), 1)


if __name__ == "__main__":
    unittest.main()
