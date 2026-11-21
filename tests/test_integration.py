"""Комплексная проверка: администратор, кассир и покупатель работают на ОДНОЙ базе данных.

Все тесты идут на временной БД (реальный cinema.db не затрагивается). Время подменено:
«сейчас» — 16.10.2026 12:00, сеансы — 17.10.2026.

Запуск:  python3 -m unittest tests.test_integration -v
"""
import shutil
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from database import crud, schema
from database.connection import get_connection, transaction
from services import admin_service
from services import auth_service as auth
from services import buyer_service as bs
from services import cashier_service as cs
from services import eticket
from services import genre_service as genres
from services import hall_service as halls
from services import movie_service as movies
from services import report_service as reports
from services import session_service as sessions
from services import ticket_service as tickets
from services.errors import PermissionDenied, ServiceError, ValidationError
from services.permissions import Role

NOW = datetime(2026, 10, 16, 12, 0)
DAY = "2026-10-16"          # день операций
SHOW_DAY = "2026-10-17"     # день сеансов
CARD = {"number": "4242 4242 4242 4242", "holder": "IVAN PETROV", "expiry": "12/30", "cvc": "123"}
POSTER_SRC = Path(__file__).resolve().parent.parent / "demo_posters" / "alice_wonderland@small.png"


class World(unittest.TestCase):
    """Пустая БД + три роли. Никаких глобальных путей: везде явный db_path."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.db = self.tmp / "integration.db"
        for p in (patch("services.clock.now", return_value=NOW),
                  patch("services.movie_service.POSTERS_DIR", self.tmp / "posters")):
            p.start()
            self.addCleanup(p.stop)
        auth.ensure_default_admin(self.db)
        self.admin = auth.login("admin", "admin123", self.db)
        auth.create_user_account(self.admin, "kassa", "kassa123", Role.CASHIER, "Кассир Анна", db_path=self.db)
        auth.create_user_account(self.admin, "kassa2", "kassa123", Role.CASHIER, "Кассир Борис", db_path=self.db)
        auth.create_user_account(self.admin, "buyer", "buyer123", Role.VIEWER, "Покупатель Пётр", db_path=self.db)
        auth.create_user_account(self.admin, "buyer2", "buyer123", Role.VIEWER, "Покупатель Ольга", db_path=self.db)
        self.cashier = auth.login("kassa", "kassa123", self.db)
        self.cashier2 = auth.login("kassa2", "kassa123", self.db)
        self.buyer = auth.login("buyer", "buyer123", self.db)
        self.buyer2 = auth.login("buyer2", "buyer123", self.db)

    def tearDown(self):
        self._tmp.cleanup()

    # --- помощники
    def sql(self, query, *params):
        conn = get_connection(self.db)
        try:
            return conn.execute(query, params).fetchall()
        finally:
            conn.close()

    def scalar(self, query, *params):
        return self.sql(query, *params)[0][0]

    def make_hall(self, name="Зал 1", rows=5, per_row=10, vip=""):
        self.hall_id = halls.create_hall(self.admin, name, rows, per_row, vip, self.db)
        scheme = halls.get_hall_scheme(self.admin, self.hall_id, self.db)
        self.seat_ids = [s["id"] for row in scheme["rows"] for s in row["seats"]]
        return self.hall_id

    def make_show(self, title="Дюна", price=500, time="18:00", hall_id=None, poster=None):
        """Администратор создаёт жанр (если нужно), фильм и сеанс. Возвращает (movie_id, session_id)."""
        genre_id = next((g["id"] for g in genres.list_genres(self.admin, self.db) if g["name"] == "Фантастика"), None) \
            or genres.create_genre(self.admin, "Фантастика", self.db)
        movie_id = movies.create_movie(self.admin, title, genre_id, 155, "12+", f"Описание: {title}",
                                       poster, self.db)
        session_id = sessions.create_session(self.admin, movie_id, hall_id or self.hall_id, SHOW_DAY, time,
                                             price, self.db)
        return movie_id, session_id

    def open_shift(self, cashier=None):
        return cs.open_shift(cashier or self.cashier, self.db)

    def cash_sale(self, session_id, seat_indexes, cashier=None, client=None, method="cash"):
        return cs.sell(cashier or self.cashier, session_id, [self.seat_ids[i] for i in seat_indexes], method,
                       client, self.db)

    def buy(self, session_id, seat_indexes, buyer=None):
        return bs.place_order(buyer or self.buyer, session_id, [self.seat_ids[i] for i in seat_indexes], CARD, self.db)

    def revenue(self, date_from=DAY, date_to=DAY):
        return reports.revenue_report(self.admin, date_from, date_to, self.db)["summary"]


# ------------------------------------------------------------------ 2.1  администратор -> покупатель и кассир

class AdminToOthersTests(World):
    def test_new_movie_and_session_visible_to_buyer_and_cashier(self):
        self.make_hall("Зал Красный", 4, 8, vip="4")
        movie_id, session_id = self.make_show("Звёздный путь", 450, poster=str(POSTER_SRC))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM movies"), 1)

        # покупатель: афиша и страница фильма
        shown = bs.catalog(self.buyer, db_path=self.db)
        self.assertEqual([m["title"] for m in shown], ["Звёздный путь"])
        m = shown[0]
        self.assertEqual((m["genre_name"], m["duration"], m["age_rating"], m["min_price"]),
                         ("Фантастика", 155, "12+", 450))
        self.assertEqual(m["description"], "Описание: Звёздный путь")
        self.assertTrue(m["poster_path"].startswith("posters/"))
        self.assertTrue(movies.poster_file(m["poster_path"]).is_file(), "постер реально скопирован")
        page = bs.movie_page(self.buyer, movie_id, self.db)
        self.assertEqual(list(page["days"]), [SHOW_DAY])
        s = page["days"][SHOW_DAY][0]
        self.assertEqual((s["id"], s["session_time"], s["hall_name"], s["price"]),
                         (session_id, "18:00", "Зал Красный", 450))

        # места: 4×8, последний ряд — VIP; все свободны
        seat_map = tickets.get_session_seat_map(self.buyer, session_id, self.db)
        flat = [x for row in seat_map["rows"] for x in row["seats"]]
        self.assertEqual(len(flat), 32)
        self.assertEqual(sum(1 for x in flat if x["seat_type"] == "vip"), 8)
        self.assertFalse(any(x["is_sold"] for x in flat))

        # кассир видит тот же фильм и сеанс
        self.open_shift()
        sellable = cs.list_sellable_movies(self.cashier, self.db)
        self.assertEqual([x["title"] for x in sellable], ["Звёздный путь"])
        self.assertEqual(sellable[0]["free_seats"], 32)
        self.assertEqual([x["id"] for x in cs.list_movie_days(self.cashier, movie_id, self.db)[SHOW_DAY]], [session_id])

    def test_cancelled_session_disappears_for_buyer_and_cashier_and_cannot_be_bought(self):
        self.make_hall()
        movie_id, session_id = self.make_show()
        admin_service.cancel_session(self.admin, session_id, self.db)
        self.open_shift()
        self.assertEqual(bs.catalog(self.buyer, db_path=self.db), [])
        self.assertEqual(cs.list_sellable_movies(self.cashier, self.db), [])
        with self.assertRaises(ValidationError):
            self.buy(session_id, [0])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 0)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 0)

    def test_movie_without_sessions_not_in_catalog(self):
        self.make_hall()
        genre_id = genres.create_genre(self.admin, "Драма", self.db)
        movies.create_movie(self.admin, "Без сеансов", genre_id, 100, "6+", db_path=self.db)
        self.assertEqual(bs.catalog(self.buyer, db_path=self.db), [])


# ------------------------------------------------------------------ 2.2  покупка покупателем

class BuyerPurchaseTests(World):
    def setUp(self):
        super().setUp()
        self.make_hall()
        self.movie_id, self.session_id = self.make_show("Дюна", 500)
        self.open_shift()

    def test_buyer_purchase_is_seen_by_cashier_and_admin(self):
        result = self.buy(self.session_id, [0, 1, 2])
        self.assertEqual(result["total"], 1500)
        self.assertEqual(len(result["tickets"]), 3)
        # SQLite: заказ + 3 билета, привязанные к заказу и покупателю
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 1)
        rows = self.sql("SELECT order_id, sale_id, status, seller_id, client_id FROM tickets")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["order_id"] == result["order_id"] and r["sale_id"] is None
                            and r["status"] == "sold" and r["seller_id"] == self.buyer.id
                            and r["client_id"] == self.buyer.client_id for r in rows))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sales"), 0)      # это не касса

        # кассир находит продажу: фильм, сеанс, места, цена, покупатель
        found = cs.search_tickets(self.cashier, movie="дюн", db_path=self.db)
        self.assertEqual(len(found), 3)
        self.assertEqual({t["movie_title"] for t in found}, {"Дюна"})
        self.assertEqual({t["session_id"] for t in found}, {self.session_id})
        self.assertEqual({t["price"] for t in found}, {500})
        self.assertEqual({t["client_name"] for t in found}, {"Покупатель Пётр"})
        self.assertEqual(sorted((t["row_number"], t["seat_number"]) for t in found), [(1, 1), (1, 2), (1, 3)])

        # администратор: поиск билетов, панель, отчёты
        self.assertEqual(len(tickets.search_tickets(self.admin, session_id=self.session_id, db_path=self.db)), 3)
        dash = admin_service.dashboard(self.admin, self.db)
        self.assertEqual((dash["tickets_today"], dash["revenue_today"]), (3, 1500))
        self.assertEqual(dash["recent_sales"][0]["movie"], "Дюна")
        rev = self.revenue()
        self.assertEqual((rev["tickets_sold"], rev["sales_amount"], rev["net_revenue"]), (3, 1500, 1500))
        by_cashier = reports.cashier_report(self.admin, DAY, DAY, self.db)["tables"]["by_cashier"]["rows"]
        self.assertEqual([(r["cashier"], r["tickets_sold"], r["sales_amount"]) for r in by_cashier],
                         [("Покупатели (онлайн)", 3, 1500)])
        # статистика кассира: покупка онлайн в его смену не попадает
        self.assertEqual(cs.shift_summary(self.cashier, db_path=self.db)["tickets_sold"], 0)

    def test_cashier_cannot_resell_buyers_seat(self):
        self.buy(self.session_id, [4])
        quote = cs.quote(self.cashier, self.session_id, [self.seat_ids[4], self.seat_ids[5]], self.db)
        self.assertEqual(quote["unavailable"], [self.seat_ids[4]])
        self.assertEqual(quote["total"], 500)
        with self.assertRaises(ValidationError) as ctx:
            self.cash_sale(self.session_id, [4, 5])
        self.assertIn("занято", str(ctx.exception))
        # «всё или ничего»: свободное место 5 тоже не продано, чек не создан
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sales"), 0)

    def test_buyer_history_and_tickets(self):
        result = self.buy(self.session_id, [0, 1])
        orders = bs.list_my_orders(self.buyer, db_path=self.db)
        self.assertEqual([(o["id"], o["tickets_sold"], o["total"]) for o in orders][:1], [(result["order_id"], 2, 1000)])
        mine = bs.my_tickets(self.buyer, "upcoming", self.db)
        self.assertEqual(len(mine), 2)
        self.assertEqual(bs.my_tickets(self.buyer2, db_path=self.db), [])        # чужие заказы не видны
        self.assertEqual(bs.list_my_orders(self.buyer2, db_path=self.db), [])

    def test_eticket_for_bought_tickets(self):
        result = self.buy(self.session_id, [0])
        html = eticket.eticket_html(bs.get_order_tickets(self.buyer, result["order_id"], self.db))
        self.assertIn("Дюна", html)
        self.assertIn("Электронный билет", html)
        self.assertNotIn("ВОЗВРАЩЁН", html)
        with self.assertRaises(ServiceError):                                  # чужой заказ недоступен
            bs.get_order_tickets(self.buyer2, result["order_id"], self.db)


# ------------------------------------------------------------------ 2.3  продажа кассиром

class CashierSaleTests(World):
    def setUp(self):
        super().setUp()
        self.make_hall()
        self.movie_id, self.session_id = self.make_show("Дюна", 500)
        self.open_shift()

    def test_cashier_sale_blocks_buyer_and_is_seen_by_admin(self):
        sale = self.cash_sale(self.session_id, [0, 1], client={"full_name": "Иван Сидоров", "phone": "+7 900 111-22-33"})
        self.assertEqual(sale["total"], 1000)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sales"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 0)

        # покупатель: места заняты, оформить нельзя, ничего не записано
        quote = bs.quote(self.buyer, self.session_id, [self.seat_ids[0], self.seat_ids[2]], self.db)
        self.assertEqual(quote["unavailable"], [self.seat_ids[0]])
        with self.assertRaises(ValidationError):
            self.buy(self.session_id, [0, 2])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 0)
        self.assertEqual(bs.my_tickets(self.buyer, db_path=self.db), [])

        # администратор видит операцию кассира и общую статистику
        found = tickets.search_tickets(self.admin, session_id=self.session_id, db_path=self.db)
        self.assertEqual(len(found), 2)
        dash = admin_service.dashboard(self.admin, self.db)
        self.assertEqual((dash["tickets_today"], dash["revenue_today"]), (2, 1000))
        row = reports.cashier_report(self.admin, DAY, DAY, self.db)["tables"]["by_cashier"]["rows"][0]
        self.assertEqual((row["cashier"], row["tickets_sold"], row["sales_amount"]), ("Кассир Анна (kassa)", 2, 1000))

    def test_cashier_without_open_shift_cannot_sell(self):
        with self.assertRaises(ValidationError):
            self.cash_sale(self.session_id, [0], cashier=self.cashier2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 0)

    def test_new_session_made_by_admin_is_sellable_at_once(self):
        _, second = self.make_show("Ёлки", 300, time="21:00")
        sale = cs.sell(self.cashier, second, [self.seat_ids[7]], "card", None, self.db)
        self.assertEqual(sale["total"], 300)
        self.assertEqual(admin_service.dashboard(self.admin, self.db)["revenue_today"], 300)


# ------------------------------------------------------------------ возвраты

class RefundTests(World):
    def setUp(self):
        super().setUp()
        self.make_hall()
        self.movie_id, self.session_id = self.make_show("Дюна", 500)
        self.open_shift()

    def test_A_buyer_refund_seen_by_cashier_and_admin(self):
        result = self.buy(self.session_id, [0, 1])
        ticket_id = result["tickets"][0]["id"]
        done = bs.refund(self.buyer, ticket_id, self.db)
        self.assertEqual(done["status"], "returned")
        row = self.sql("SELECT status, returned_at, refunded_by FROM tickets WHERE id=?", ticket_id)[0]
        self.assertEqual((row["status"], row["refunded_by"]), ("returned", self.buyer.id))
        self.assertTrue(row["returned_at"])
        # исходная запись о покупке сохранена
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 2)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 1)
        self.assertEqual(self.sql("SELECT total FROM orders")[0][0], 1000)
        # покупатель
        self.assertEqual([t["id"] for t in bs.my_tickets(self.buyer, "returned", self.db)], [ticket_id])
        self.assertEqual(bs.list_my_orders(self.buyer, db_path=self.db)[0]["status"], "partial")
        # кассир видит статус возврата
        seen = cs.search_tickets(self.cashier, ticket_id=ticket_id, db_path=self.db)[0]
        self.assertEqual(seen["status"], "returned")
        # администратор: поиск и финансы
        self.assertEqual(tickets.get_ticket(self.admin, ticket_id, self.db)["status"], "returned")
        rev = self.revenue()
        self.assertEqual((rev["tickets_sold"], rev["tickets_returned"], rev["net_revenue"]), (2, 1, 500))
        dash = admin_service.dashboard(self.admin, self.db)
        self.assertEqual((dash["tickets_today"], dash["returns_today"], dash["revenue_today"]), (2, 1, 500))
        # место освободилось и его можно продать ещё раз
        free = cs.quote(self.cashier, self.session_id, [self.seat_ids[0]], self.db)
        self.assertEqual(free["unavailable"], [])
        resold = self.cash_sale(self.session_id, [0])
        self.assertEqual(resold["total"], 500)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 3)        # история не удалена

    def test_B_cashier_refund_seen_by_buyer_and_admin(self):
        sale = self.cash_sale(self.session_id, [0, 1], client={"full_name": "Иван"})
        ticket_id = sale["tickets"][0]["id"]
        done = cs.refund(self.cashier, ticket_id, self.db)
        self.assertEqual(done["status"], "returned")
        self.assertEqual(self.sql("SELECT refunded_by FROM tickets WHERE id=?", ticket_id)[0][0], self.cashier.id)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM sales"), 1)            # чек остался
        summary = cs.shift_summary(self.cashier, db_path=self.db)
        self.assertEqual((summary["tickets_sold"], summary["returns_count"], summary["net_amount"]), (2, 1, 500))
        rev = self.revenue()
        self.assertEqual((rev["sales_amount"], rev["refund_amount"], rev["net_revenue"]), (1000, 500, 500))

    def test_B2_buyer_sees_ticket_returned_by_cashier(self):
        result = self.buy(self.session_id, [3])
        ticket_id = result["tickets"][0]["id"]
        cs.refund(self.cashier, ticket_id, self.db)
        mine = bs.my_tickets(self.buyer, db_path=self.db)
        self.assertEqual([(t["id"], t["status"], t["group"]) for t in mine], [(ticket_id, "returned", "returned")])
        self.assertEqual(bs.list_my_orders(self.buyer, db_path=self.db)[0]["status"], "returned")
        html = eticket.eticket_html(bs.get_order_tickets(self.buyer, result["order_id"], self.db))
        self.assertIn("ВОЗВРАЩЁН", html)
        self.assertEqual(self.revenue()["net_revenue"], 0)

    def test_C_repeat_refund_refused(self):
        bought = self.buy(self.session_id, [0])["tickets"][0]["id"]
        sold = self.cash_sale(self.session_id, [1])["tickets"][0]["id"]
        bs.refund(self.buyer, bought, self.db)
        cs.refund(self.cashier, sold, self.db)
        before = self.revenue()
        for call in (lambda: bs.refund(self.buyer, bought, self.db),
                     lambda: cs.refund(self.cashier, bought, self.db),
                     lambda: tickets.refund_ticket(self.admin, bought, self.db),
                     lambda: cs.refund(self.cashier, sold, self.db),
                     lambda: tickets.refund_ticket(self.admin, sold, self.db)):
            with self.assertRaises(ValidationError) as ctx:
                call()
            self.assertIn("возвращ", str(ctx.exception).lower())
        self.assertEqual(self.revenue(), before)                                # деньги не списаны дважды
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets WHERE status='returned'"), 2)

    def test_refund_after_session_start_refused(self):
        ticket_id = self.buy(self.session_id, [0])["tickets"][0]["id"]
        with patch("services.clock.now", return_value=datetime(2026, 10, 17, 18, 30)):
            for call in (lambda: bs.refund(self.buyer, ticket_id, self.db),
                         lambda: cs.refund(self.cashier, ticket_id, self.db)):
                with self.assertRaises(ValidationError):
                    call()
        self.assertEqual(self.scalar("SELECT status FROM tickets WHERE id=?", ticket_id), "sold")

    def test_buyer_cannot_refund_foreign_ticket(self):
        ticket_id = self.buy(self.session_id, [0])["tickets"][0]["id"]
        with self.assertRaises(PermissionDenied):
            bs.refund(self.buyer2, ticket_id, self.db)
        with self.assertRaises(PermissionDenied):
            tickets.refund_own_ticket(self.buyer2, ticket_id, self.db)
        cashier_ticket = self.cash_sale(self.session_id, [1])["tickets"][0]["id"]
        with self.assertRaises(PermissionDenied):
            bs.refund(self.buyer, cashier_ticket, self.db)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets WHERE status='returned'"), 0)


# ------------------------------------------------------------------ финансы

class FinanceTests(World):
    def setUp(self):
        super().setUp()
        self.make_hall("Зал 1", 5, 10)
        self.movie_id, self.session_id = self.make_show("Дюна", 500)
        self.open_shift()

    def test_ten_tickets_two_returned_is_4000(self):
        sale = self.cash_sale(self.session_id, range(0, 6))                    # 6 — касса
        order = self.buy(self.session_id, range(6, 10))                        # 4 — онлайн
        self.assertEqual(sale["total"] + order["total"], 5000)
        cs.refund(self.cashier, sale["tickets"][0]["id"], self.db)             # возврат кассиром
        bs.refund(self.buyer, order["tickets"][0]["id"], self.db)             # возврат покупателем
        s = self.revenue()
        self.assertEqual((s["tickets_sold"], s["sales_amount"], s["tickets_returned"], s["refund_amount"],
                          s["net_revenue"]), (10, 5000, 2, 1000, 4000))
        # по фильму, залу и дням те же цифры, без двойного счёта
        tables = reports.revenue_report(self.admin, DAY, DAY, self.db)["tables"]
        for name in ("by_movie", "by_hall", "by_day"):
            self.assertEqual(tables[name]["totals"]["net_revenue"], 4000, name)
        self.assertEqual(tables["by_movie"]["rows"][0]["tickets_sold"], 10)
        # по кассирам: кассир продал 6 (из них 1 вернули), онлайн — 4 (1 вернули)
        rows = {r["cashier"]: r for r in reports.cashier_report(self.admin, DAY, DAY, self.db)["tables"]["by_cashier"]["rows"]}
        self.assertEqual((rows["Кассир Анна (kassa)"]["tickets_sold"], rows["Кассир Анна (kassa)"]["net_revenue"]), (6, 2500))
        self.assertEqual((rows["Покупатели (онлайн)"]["tickets_sold"], rows["Покупатели (онлайн)"]["net_revenue"]), (4, 1500))
        # неделя и месяц дают то же
        self.assertEqual(self.revenue("2026-10-10", "2026-10-16")["net_revenue"], 4000)
        self.assertEqual(self.revenue("2026-10-01", "2026-10-31")["net_revenue"], 4000)
        # панель администратора и итоги смены кассира (только его продажи и возвраты)
        dash = admin_service.dashboard(self.admin, self.db)
        self.assertEqual((dash["tickets_today"], dash["returns_today"], dash["revenue_today"]), (10, 2, 4000))
        shift = cs.shift_summary(self.cashier, db_path=self.db)
        self.assertEqual((shift["tickets_sold"], shift["sales_amount"], shift["returns_count"],
                          shift["refund_amount"], shift["net_amount"]), (6, 3000, 1, 500, 2500))
        # реальные активные билеты в БД: 8 × 500
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets WHERE status='sold'"), 8)
        self.assertEqual(self.scalar("SELECT SUM(s.price) FROM tickets t JOIN sessions s ON s.id=t.session_id "
                                     "WHERE t.status='sold'"), 4000)

    def test_cashier_report_is_not_visible_to_cashier_or_buyer(self):
        for user in (self.cashier, self.buyer):
            with self.assertRaises(PermissionDenied):
                reports.revenue_report(user, DAY, DAY, self.db)
            with self.assertRaises(PermissionDenied):
                reports.cashier_report(user, DAY, DAY, self.db)
            with self.assertRaises(PermissionDenied):
                admin_service.dashboard(user, self.db)

    def test_second_cashier_has_own_shift_totals(self):
        self.open_shift(self.cashier2)
        self.cash_sale(self.session_id, [0, 1], cashier=self.cashier)
        self.cash_sale(self.session_id, [2], cashier=self.cashier2)
        self.assertEqual(cs.shift_summary(self.cashier, db_path=self.db)["sales_amount"], 1000)
        self.assertEqual(cs.shift_summary(self.cashier2, db_path=self.db)["sales_amount"], 500)
        self.assertEqual(self.revenue()["sales_amount"], 1500)

    def test_shift_close_report(self):
        self.cash_sale(self.session_id, [0, 1])
        self.cash_sale(self.session_id, [2], method="card")
        sale_to_return = self.cash_sale(self.session_id, [3])["tickets"][0]["id"]
        cs.refund(self.cashier, sale_to_return, self.db)
        closed = cs.close_shift(self.cashier, self.db)
        self.assertFalse(closed["is_open"])
        self.assertEqual((closed["tickets_sold"], closed["sales_amount"], closed["returns_count"],
                          closed["refund_amount"], closed["net_amount"]), (4, 2000, 1, 500, 1500))
        by = {m["method"]: m for m in closed["by_method"]}
        self.assertEqual((by["cash"]["net"], by["card"]["net"]), (1000, 500))
        self.assertIsNone(cs.current_shift(self.cashier, self.db))
        with self.assertRaises(ValidationError):                               # после закрытия продавать нельзя
            self.cash_sale(self.session_id, [5])
        with self.assertRaises(ValidationError):
            cs.close_shift(self.cashier, self.db)
        self.assertIn("1", cs.shift_report_text(closed, "Кассир Анна"))
        self.assertEqual(len(cs.list_my_shifts(self.cashier, self.db)), 1)


# ------------------------------------------------------------------ места и одновременные покупки

class SeatTests(World):
    def setUp(self):
        super().setUp()
        self.make_hall("Зал 1", 3, 4, vip="3")
        self.movie_id, self.session_id = self.make_show("Дюна", 500)
        self.open_shift()

    def test_seat_states_follow_sales_and_refunds(self):
        def states():
            data = tickets.get_session_seat_map(self.admin, self.session_id, self.db)
            return {s["id"]: s["is_sold"] for row in data["rows"] for s in row["seats"]}
        self.assertFalse(any(states().values()))
        a = self.cash_sale(self.session_id, [0])["tickets"][0]["id"]
        b = self.buy(self.session_id, [1])["tickets"][0]["id"]
        st = states()
        self.assertTrue(st[self.seat_ids[0]] and st[self.seat_ids[1]])
        self.assertEqual(sum(st.values()), 2)
        cs.refund(self.cashier, a, self.db)
        bs.refund(self.buyer, b, self.db)
        self.assertFalse(any(states().values()))

    def test_vip_price_and_seat_types(self):
        data = tickets.get_session_seat_map(self.buyer, self.session_id, self.db)
        vip = [s for row in data["rows"] for s in row["seats"] if s["seat_type"] == "vip"]
        self.assertEqual(len(vip), 4)
        quote_b = bs.quote(self.buyer, self.session_id, [self.seat_ids[0], vip[0]["id"]], self.db)
        quote_c = cs.quote(self.cashier, self.session_id, [self.seat_ids[0], vip[0]["id"]], self.db)
        self.assertEqual(quote_b["total"], quote_c["total"])        # обе роли считают цену одинаково
        self.assertEqual(quote_b["count"], 2)

    def test_two_threads_buy_same_seat_only_one_wins(self):
        for round_no in range(5):                                   # несколько раундов, чтобы поймать гонку
            seat = self.seat_ids[round_no]
            barrier = threading.Barrier(3)
            results = {}

            def worker(name, action):
                barrier.wait()
                try:
                    results[name] = ("ok", action())
                except ServiceError as exc:
                    results[name] = ("fail", str(exc))

            threads = [
                threading.Thread(target=worker, args=("buyer", lambda: bs.place_order(
                    self.buyer, self.session_id, [seat], CARD, self.db))),
                threading.Thread(target=worker, args=("buyer2", lambda: bs.place_order(
                    self.buyer2, self.session_id, [seat], CARD, self.db))),
                threading.Thread(target=worker, args=("cashier", lambda: cs.sell(
                    self.cashier, self.session_id, [seat], "cash", None, self.db))),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
                self.assertFalse(t.is_alive(), "поток завис")
            wins = [n for n, (state, _) in results.items() if state == "ok"]
            self.assertEqual(len(wins), 1, results)
            self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets WHERE seat_id=? AND session_id=? AND status='sold'",
                                         seat, self.session_id), 1)
        # проигравшие не оставили «хвостов»: каждому билету соответствует ровно один заказ или чек
        total = self.scalar("SELECT COUNT(*) FROM tickets")
        self.assertEqual(total, 5)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders") + self.scalar("SELECT COUNT(*) FROM sales"), 5)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets WHERE order_id IS NULL AND sale_id IS NULL"), 0)

    def test_database_unique_index_is_last_line_of_defence(self):
        self.cash_sale(self.session_id, [0])
        conn = get_connection(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO tickets (session_id, seat_id, client_id, purchase_date, status) "
                             "VALUES (?, ?, 1, '2026-10-16 12:00:00', 'sold')", (self.session_id, self.seat_ids[0]))
        finally:
            conn.close()
        # а после возврата тот же INSERT проходит (индекс частичный)
        ticket_id = self.sql("SELECT id FROM tickets")[0][0]
        cs.refund(self.cashier, ticket_id, self.db)
        self.cash_sale(self.session_id, [0])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets WHERE seat_id=?", self.seat_ids[0]), 2)

    def test_failed_purchase_leaves_no_trace(self):
        self.cash_sale(self.session_id, [2])
        bad_card = dict(CARD, number="4242 4242 4242 4241")
        with self.assertRaises(ValidationError):
            bs.place_order(self.buyer, self.session_id, [self.seat_ids[3]], bad_card, self.db)
        with self.assertRaises(ValidationError):                              # одно из мест занято
            self.buy(self.session_id, [3, 2])
        with self.assertRaises(ValidationError):                              # место из чужого зала
            hall2 = halls.create_hall(self.admin, "Зал 2", 1, 2, "", self.db)
            other = [s["id"] for row in halls.get_hall_scheme(self.admin, hall2, self.db)["rows"] for s in row["seats"]]
            bs.place_order(self.buyer, self.session_id, [other[0]], CARD, self.db)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 1)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM orders"), 0)
        free = cs.quote(self.cashier, self.session_id, [self.seat_ids[3]], self.db)
        self.assertEqual(free["unavailable"], [])                             # место 3 не «залипло»

    def test_session_started_blocks_both_roles(self):
        with patch("services.clock.now", return_value=datetime(2026, 10, 17, 18, 0)):
            with self.assertRaises(ValidationError):
                self.buy(self.session_id, [0])
            with self.assertRaises(ValidationError):
                self.cash_sale(self.session_id, [0])
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 0)


# ------------------------------------------------------------------ права при прямых вызовах сервисов

class PermissionTamperingTests(World):
    def setUp(self):
        super().setUp()
        self.make_hall()
        self.movie_id, self.session_id = self.make_show("Дюна", 500)
        self.open_shift()
        self.genre_id = genres.list_genres(self.admin, self.db)[0]["id"]

    def denied(self, call):
        with self.assertRaises(PermissionDenied):
            call()

    def test_buyer_cannot_do_staff_or_admin_actions(self):
        b, db = self.buyer, self.db
        self.denied(lambda: movies.create_movie(b, "X", self.genre_id, 90, "0+", db_path=db))
        self.denied(lambda: movies.delete_movie(b, self.movie_id, db))
        self.denied(lambda: sessions.create_session(b, self.movie_id, self.hall_id, SHOW_DAY, "21:00", 100, db))
        self.denied(lambda: halls.create_hall(b, "Зал X", 1, 1, "", db))
        self.denied(lambda: genres.create_genre(b, "Жанр", db))
        self.denied(lambda: auth.create_user_account(b, "evil", "secret1", Role.ADMIN, "Evil", db_path=db))
        self.denied(lambda: auth.list_user_accounts(b, db))
        self.denied(lambda: cs.open_shift(b, db))
        self.denied(lambda: cs.sell(b, self.session_id, [self.seat_ids[0]], "cash", None, db))
        self.denied(lambda: cs.refund(b, 1, db))
        self.denied(lambda: tickets.refund_ticket(b, 1, db))
        self.denied(lambda: tickets.search_tickets(b, db_path=db))
        self.denied(lambda: reports.revenue_report(b, DAY, DAY, db))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM users WHERE username='evil'"), 0)

    def test_cashier_cannot_do_admin_or_buyer_actions(self):
        c, db = self.cashier, self.db
        self.denied(lambda: movies.create_movie(c, "X", self.genre_id, 90, "0+", db_path=db))
        self.denied(lambda: sessions.delete_session(c, self.session_id, db))
        self.denied(lambda: halls.delete_hall(c, self.hall_id, db))
        self.denied(lambda: auth.create_user_account(c, "evil", "secret1", Role.ADMIN, "Evil", db_path=db))
        self.denied(lambda: auth.set_user_role(c, self.buyer.id, Role.ADMIN, db))
        self.denied(lambda: reports.cashier_report(c, DAY, DAY, db))
        self.denied(lambda: admin_service.dashboard(c, db))
        self.denied(lambda: admin_service.cancel_session(c, self.session_id, db))
        self.denied(lambda: bs.place_order(c, self.session_id, [self.seat_ids[0]], CARD, db))
        self.denied(lambda: bs.my_tickets(c, db_path=db))
        self.denied(lambda: tickets.refund_own_ticket(c, 1, db))

    def test_admin_does_not_get_buyer_or_cashier_desk(self):
        a, db = self.admin, self.db
        self.denied(lambda: cs.open_shift(a, db))
        self.denied(lambda: bs.place_order(a, self.session_id, [self.seat_ids[0]], CARD, db))
        self.denied(lambda: bs.home(a, db))

    def test_parameter_tampering_in_sell_tickets(self):
        db = self.db
        # покупатель пытается купить «на чужого клиента» и с кассовым чеком
        self.denied(lambda: tickets.sell_tickets(self.buyer, self.session_id, [self.seat_ids[0]], self.buyer2.client_id,
                                                 db, sale_info={"payment_method": "cash", "shift_id": 1}))
        self.denied(lambda: tickets.sell_tickets(self.cashier, self.session_id, [self.seat_ids[0]], None,
                                                 db, order_info={"payment_method": "card"}))
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 0)
        made = tickets.sell_tickets(self.buyer, self.session_id, [self.seat_ids[1]], self.buyer2.client_id, db,
                                    order_info={"payment_method": "card"})
        self.assertEqual(self.scalar("SELECT client_id FROM tickets WHERE id=?", made[0]["id"]), self.buyer.client_id)

    def test_tampered_inputs_rejected(self):
        for bad in ([], "abc", None, [0], [-5], [10 ** 9]):
            with self.assertRaises(ServiceError):
                bs.place_order(self.buyer, self.session_id, bad, CARD, self.db)
        with self.assertRaises(ServiceError):
            bs.place_order(self.buyer, 999999, [self.seat_ids[0]], CARD, self.db)
        with self.assertRaises(ValidationError):
            cs.sell(self.cashier, self.session_id, [self.seat_ids[0]], "bitcoin", None, self.db)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 0)

    def test_buyer_cannot_see_foreign_ticket(self):
        ticket_id = self.cash_sale(self.session_id, [0])["tickets"][0]["id"]
        with self.assertRaises(PermissionDenied):
            tickets.get_ticket(self.buyer, ticket_id, self.db)


# ------------------------------------------------------------------ регистрация и вход

class AuthTests(World):
    def test_login_of_all_roles_and_roles_are_separated(self):
        self.assertEqual(self.admin.role, Role.ADMIN)
        self.assertEqual(self.cashier.role, Role.CASHIER)
        self.assertEqual(self.buyer.role, Role.VIEWER)
        self.assertIsNotNone(self.buyer.client_id)
        self.assertIsNone(self.cashier.client_id)
        with self.assertRaises(ServiceError):
            auth.login("kassa", "wrong", self.db)
        with self.assertRaises(ServiceError):
            auth.login("nobody", "x", self.db)

    def test_new_buyer_registered_by_admin_can_buy_at_once(self):
        make_hall = self.make_hall()
        _, session_id = self.make_show()
        auth.create_user_account(self.admin, "newbie", "secret1", Role.VIEWER, "Новый Покупатель", db_path=self.db)
        newbie = auth.login("newbie", "secret1", self.db)
        result = bs.place_order(newbie, session_id, [self.seat_ids[0]], CARD, self.db)
        self.assertEqual(result["total"], 500)
        self.assertEqual(self.scalar("SELECT created_at IS NOT NULL FROM users WHERE username='newbie'"), 1)
        self.assertEqual(make_hall, self.hall_id)

    def test_passwords_are_hashed_and_blocked_user_cannot_login(self):
        for row in self.sql("SELECT username, password_hash FROM users"):
            self.assertNotIn(row["username"] + "123", row["password_hash"])
            self.assertNotIn("kassa123", row["password_hash"])
            self.assertNotIn("buyer123", row["password_hash"])
        auth.set_user_active(self.admin, self.buyer.id, False, self.db)
        with self.assertRaises(ServiceError):
            auth.login("buyer", "buyer123", self.db)


# ------------------------------------------------------------------ аудит БД

class DatabaseAuditTests(World):
    def test_foreign_keys_pragma_on_every_connection(self):
        conn = get_connection(self.db)
        try:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):         # нарушение ссылки реально отклоняется
                conn.execute("INSERT INTO tickets (session_id, seat_id, client_id, purchase_date, status) "
                             "VALUES (9999, 9999, 9999, '2026-10-16 12:00:00', 'sold')")
        finally:
            conn.close()
        with transaction(self.db) as conn:
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_expected_tables_indexes_and_integrity(self):
        self.make_hall()
        self.make_show()
        self.open_shift()
        self.cash_sale(self.session_id_of_first(), [0])
        self.buy(self.session_id_of_first(), [1])
        names = {r[0] for r in self.sql("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"users", "clients", "genres", "movies", "halls", "seats", "sessions", "tickets",
                         "shifts", "sales", "orders"} <= names, names)
        indexes = {r[0] for r in self.sql("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("ux_tickets_session_seat_sold", indexes)
        self.assertIn("ux_shifts_one_open", indexes)
        self.assertEqual(self.sql("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.scalar("PRAGMA integrity_check"), "ok")
        # связи пользователь -> заказ/чек -> билет -> сеанс -> место целы
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM tickets t JOIN sessions s ON s.id=t.session_id JOIN seats p ON p.id=t.seat_id "
            "AND p.hall_id=s.hall_id JOIN users u ON u.id=t.seller_id"), 2)
        # время и цены хранятся в едином формате
        self.assertRegex(self.scalar("SELECT purchase_date FROM tickets LIMIT 1"), r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        self.assertEqual(self.scalar("SELECT price FROM sessions LIMIT 1"), 500)

    def session_id_of_first(self):
        return self.scalar("SELECT id FROM sessions ORDER BY id LIMIT 1")

    def test_schema_init_is_idempotent_and_keeps_data(self):
        self.make_hall()
        self.make_show()
        self.open_shift()
        self.cash_sale(self.session_id_of_first(), [0])
        before = {t: self.scalar(f"SELECT COUNT(*) FROM {t}") for t in ("users", "movies", "sessions", "tickets", "sales")}
        for _ in range(2):                       # повторный запуск при каждом старте программы
            schema.init_db(self.db)
        after = {t: self.scalar(f"SELECT COUNT(*) FROM {t}") for t in before}
        self.assertEqual(before, after)
        self.assertEqual(self.sql("PRAGMA foreign_key_check"), [])

    def test_cannot_delete_session_or_hall_with_sold_tickets(self):
        self.make_hall()
        movie_id, session_id = self.make_show()
        self.open_shift()
        self.cash_sale(session_id, [0])
        with self.assertRaises(ServiceError):
            sessions.delete_session(self.admin, session_id, self.db)
        with self.assertRaises(ServiceError):
            halls.delete_hall(self.admin, self.hall_id, self.db)
        with self.assertRaises(ServiceError):
            movies.delete_movie(self.admin, movie_id, self.db)
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 1)


# ------------------------------------------------------------------ сквозные сценарии

class EndToEndTests(World):
    def run_flow(self, via_buyer: bool):
        # 1. админ создаёт фильм и сеанс
        self.make_hall("Зал Е2Е", 4, 6)
        movie_id, session_id = self.make_show("Сквозной фильм", 400, poster=str(POSTER_SRC))
        self.open_shift()
        # 2. покупатель видит и выбирает; 3. покупка (или продажа в кассе)
        film = bs.movie_page(self.buyer, movie_id, self.db)["movie"]
        self.assertEqual(film["title"], "Сквозной фильм")
        if via_buyer:
            made = self.buy(session_id, [0, 1])
            ticket_ids = [t["id"] for t in made["tickets"]]
        else:
            made = self.cash_sale(session_id, [0, 1], client={"full_name": "Гость кассы"})
            ticket_ids = [t["id"] for t in made["tickets"]]
        # 4. кассир видит продажу
        seen = cs.search_tickets(self.cashier, session_id=session_id, db_path=self.db)
        self.assertEqual(sorted(t["id"] for t in seen), sorted(ticket_ids))
        if not via_buyer:
            self.assertEqual(cs.list_my_sales(self.cashier, db_path=self.db)[0]["tickets_sold"], 2)
        # 5. админ видит продажу в статистике
        self.assertEqual(self.revenue()["net_revenue"], 800)
        self.assertEqual(admin_service.dashboard(self.admin, self.db)["tickets_today"], 2)
        # 6. возврат одного билета: покупателем (онлайн) или кассиром (касса)
        if via_buyer:
            bs.refund(self.buyer, ticket_ids[0], self.db)
        else:
            cs.refund(self.cashier, ticket_ids[0], self.db)
        # 7. статус видят все
        self.assertEqual(cs.search_tickets(self.cashier, ticket_id=ticket_ids[0], db_path=self.db)[0]["status"], "returned")
        self.assertEqual(tickets.get_ticket(self.admin, ticket_ids[0], self.db)["status"], "returned")
        # 8. финансы пересчитаны
        s = self.revenue()
        self.assertEqual((s["tickets_sold"], s["tickets_returned"], s["net_revenue"]), (2, 1, 400))
        # 9. место свободно и продаётся повторно — другой стороной
        seat_freed = self.seat_ids[0]
        self.assertEqual(cs.quote(self.cashier, session_id, [seat_freed], self.db)["unavailable"], [])
        again = self.buy(session_id, [0], buyer=self.buyer2) if not via_buyer else self.cash_sale(session_id, [0])
        self.assertEqual(again["total"], 400)
        self.assertEqual(self.revenue()["net_revenue"], 800)
        # 10. история не потеряна, целостность
        self.assertEqual(self.scalar("SELECT COUNT(*) FROM tickets"), 3)
        self.assertEqual(self.sql("PRAGMA foreign_key_check"), [])
        self.assertEqual(self.scalar("PRAGMA integrity_check"), "ok")

    def test_flow_buyer_purchase(self):
        self.run_flow(via_buyer=True)

    def test_flow_cashier_sale(self):
        self.run_flow(via_buyer=False)


class ErrorDialogTextTests(unittest.TestCase):
    def test_unexpected_error_text_names_the_error(self):
        from tests import fake_tk
        saved = fake_tk.install()
        try:
            import importlib
            for name in ("palette", "theme", "neon", "common"):
                importlib.import_module(f"gui.{name}")
            common = importlib.import_module("gui.common")
            text = common.unexpected_error_text(RuntimeError("boom"))
            self.assertIn("RuntimeError: boom", text)
            self.assertIn("cinema.log", text)
            self.assertLess(len(common.unexpected_error_text(ValueError("x" * 1000))), 500)
        finally:
            fake_tk.restore(saved)


if __name__ == "__main__":
    unittest.main()
