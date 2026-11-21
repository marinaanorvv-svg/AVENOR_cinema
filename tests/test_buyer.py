"""Личный кабинет покупателя: сервисы (афиша, заказ и оплата, билеты, возврат, история, профиль, права)
и экраны на заглушке tkinter.

Запуск:  python -m unittest tests.test_buyer -v
"""
import dataclasses
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests import fake_tk
from tests import test_gui_screens as screens
from tests import test_gui_smoke as smoke


def setUpModule():
    smoke.setUpModule()


def tearDownModule():
    smoke.tearDownModule()


from database import schema                                # noqa: E402
from database.connection import get_connection             # noqa: E402
from services import auth_service as auth                  # noqa: E402
from services import buyer_service as bs                   # noqa: E402
from services import cashier_service as cs                 # noqa: E402
from services import admin_service                          # noqa: E402
from services import eticket                                # noqa: E402
from services import genre_service as genres               # noqa: E402
from services import hall_service as halls                 # noqa: E402
from services import movie_service as movies               # noqa: E402
from services import report_service as reports             # noqa: E402
from services import session_service as sessions           # noqa: E402
from services import ticket_service as tickets             # noqa: E402
from services.errors import PermissionDenied, ValidationError   # noqa: E402
from services.permissions import Permission, Role         # noqa: E402

gui = smoke.gui
CARD = {"number": "4242 4242 4242 4242", "holder": "IVAN PETROV", "expiry": "12/30", "cvc": "123"}
AFTER_START = datetime(2026, 10, 17, 19, 0)


class BuyerBase(screens.ScreenBase):
    def setUp(self):
        super().setUp()
        auth.create_user_account(self.admin, "view2", "secret1", Role.VIEWER, "Покупатель Ольга")
        self.viewer2 = auth.login("view2", "secret1")

    def order(self, seats=(0,), actor=None):
        return bs.place_order(actor or self.viewer, self.session_id, [self.seat_ids[i] for i in seats], CARD)

    def rows(self, sql, *params):
        conn = get_connection(self.db)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()


class BuyerPermissionTests(BuyerBase):
    def test_portal_only_for_buyer(self):
        self.assertTrue(self.viewer.has_permission(Permission.USE_PORTAL))
        for user in (self.admin, self.cashier):
            self.assertFalse(user.has_permission(Permission.USE_PORTAL))
            self.assertFalse(user.has_permission(Permission.REFUND_OWN_TICKET))
            for call in (lambda a: bs.home(a), lambda a: bs.catalog(a), lambda a: bs.my_tickets(a),
                         lambda a: bs.list_my_orders(a), lambda a: bs.get_profile(a),
                         lambda a: bs.place_order(a, self.session_id, [self.seat_ids[0]], CARD)):
                with self.assertRaises(PermissionDenied):
                    call(user)

    def test_buyer_still_cannot_use_staff_functions(self):
        v = self.viewer
        for permission in (Permission.USE_CASHIER_DESK, Permission.REFUND_TICKET, Permission.MANAGE_MOVIES,
                           Permission.MANAGE_USERS, Permission.VIEW_REPORTS, Permission.VIEW_ALL_TICKETS):
            self.assertFalse(v.has_permission(permission), permission)
        with self.assertRaises(PermissionDenied):
            cs.open_shift(v)
        with self.assertRaises(PermissionDenied):
            tickets.refund_ticket(v, 1)
        with self.assertRaises(PermissionDenied):
            movies.create_movie(v, "X", self.genre_id, 100, "12+")
        with self.assertRaises(PermissionDenied):
            reports.cashier_report(v, "2026-10-01", "2026-10-31")
        with self.assertRaises(PermissionDenied):
            admin_service.dashboard(v)

    def test_client_less_buyer_can_browse_but_not_buy(self):
        guest = dataclasses.replace(self.viewer, client_id=None)
        self.assertEqual([m["title"] for m in bs.catalog(guest)], ["Дюна"])
        self.assertIsNone(bs.home(guest)["next_ticket"])
        for call in (lambda: bs.my_tickets(guest), lambda: bs.quote(guest, self.session_id, [self.seat_ids[0]]),
                     lambda: bs.place_order(guest, self.session_id, [self.seat_ids[0]], CARD)):
            with self.assertRaises(ValidationError):
                call()


class BuyerCatalogTests(BuyerBase):
    def setUp(self):
        super().setUp()
        self.comedy = genres.create_genre(self.admin, "Комедия")
        self.movie2 = movies.create_movie(self.admin, "Ёлки", self.comedy, 90, "0+", "Весёлый фильм")
        self.hall2 = halls.create_hall(self.admin, "Зал 2", 1, 4)
        sessions.create_session(self.admin, self.movie2, self.hall2, "2026-10-18", "12:00", 200)

    def titles(self, **kw):
        return [m["title"] for m in bs.catalog(self.viewer, **kw)]

    def test_search_filters_and_sort(self):
        self.assertEqual(self.titles(), ["Дюна", "Ёлки"])
        self.assertEqual(self.titles(sort="title_desc"), ["Ёлки", "Дюна"])
        self.assertEqual(self.titles(search="дЮ"), ["Дюна"])
        self.assertEqual(self.titles(genre="Комедия"), ["Ёлки"])
        self.assertEqual(self.titles(age="12+"), ["Дюна"])
        self.assertEqual(self.titles(search="нет такого"), [])
        filters = bs.catalog_filters(self.viewer)
        self.assertEqual((filters["genres"], filters["ages"]), (["Драма", "Комедия"], ["0+", "12+"]))

    def test_popular_and_new_use_real_data(self):
        self.assertEqual(bs.home(self.viewer)["popular"], [])          # продаж ещё не было
        self.sell(0)
        self.sell(1)
        home = bs.home(self.viewer)
        self.assertEqual([m["title"] for m in home["popular"]], ["Дюна"])
        self.assertEqual(self.titles(sort="popular")[0], "Дюна")
        self.assertEqual({m["title"] for m in home["new"]}, {"Дюна", "Ёлки"})

    def test_cancelled_and_started_sessions_are_hidden(self):
        self.assertEqual(len(bs.movie_page(self.viewer, self.movie_id)["days"]["2026-10-17"]), 1)
        admin_service.cancel_session(self.admin, self.session_id)
        self.assertEqual(self.titles(), ["Ёлки"])
        self.assertEqual(bs.movie_page(self.viewer, self.movie_id)["days"], {})
        with patch("services.clock.now", return_value=datetime(2026, 10, 18, 13, 0)):
            self.assertEqual(self.titles(), [])
            self.assertEqual(bs.home(self.viewer)["now_showing"], [])


class BuyerOrderTests(BuyerBase):
    def test_order_saves_order_and_tickets_together(self):
        result = self.order((0, 1))
        self.assertEqual(result["total"], 600)
        order = self.rows("SELECT * FROM orders")[0]
        self.assertEqual((order["user_id"], order["client_id"], order["payment_method"], order["total"]),
                         (self.viewer.id, self.viewer.client_id, "card", 600))
        t_rows = self.rows("SELECT order_id, client_id, seller_id, status FROM tickets")
        self.assertEqual([(r["order_id"], r["client_id"], r["seller_id"], r["status"]) for r in t_rows],
                         [(order["id"], self.viewer.client_id, self.viewer.id, "sold")] * 2)
        self.assertEqual(self.count("sales"), 0)                       # кассовые продажи не затронуты
        self.assertNotIn("4242", str(self.rows("SELECT * FROM orders")[0][:]))   # номер карты не хранится

    def test_card_validation(self):
        bad = [dict(CARD, number="4242 4242 4242 4241"), dict(CARD, number="12"), dict(CARD, holder="Иван"),
               dict(CARD, expiry="13/30"), dict(CARD, expiry="01/20"), dict(CARD, expiry="abc"),
               dict(CARD, cvc="12"), {}]
        for card in bad:
            with self.assertRaises(ValidationError, msg=card):
                bs.place_order(self.viewer, self.session_id, [self.seat_ids[0]], card)
        self.assertEqual((self.count("orders"), self.count("tickets")), (0, 0))

    def test_no_double_sale_and_nothing_saved_on_failure(self):
        self.sell(0)                                                   # место уже купили на кассе
        q = bs.quote(self.viewer, self.session_id, [self.seat_ids[0], self.seat_ids[1]])
        self.assertEqual((q["count"], q["total"], q["unavailable"]), (1, 300, [self.seat_ids[0]]))
        with self.assertRaises(ValidationError):
            self.order((1, 0))
        self.assertEqual((self.count("orders"), self.count("tickets")), (0, 1))

    def test_started_and_cancelled_sessions_cannot_be_bought(self):
        with patch("services.clock.now", return_value=AFTER_START):
            with self.assertRaises(ValidationError):
                self.order()
        conn = get_connection(self.db)
        conn.execute("UPDATE sessions SET is_cancelled = 1")
        conn.commit()
        conn.close()
        with self.assertRaises(ValidationError):
            self.order()
        self.assertEqual((self.count("orders"), self.count("tickets")), (0, 0))

    def test_max_seats_and_seat_from_other_hall(self):
        with self.assertRaises(ValidationError):
            bs.quote(self.viewer, self.session_id, [999999])
        big = halls.create_hall(self.admin, "Большой", 3, 5)
        big_session = sessions.create_session(self.admin, self.movie_id, big, "2026-10-17", "21:00", 300)
        seat_ids = [s["id"] for r in tickets.get_session_seat_map(self.viewer, big_session)["rows"] for s in r["seats"]]
        with self.assertRaises(ValidationError):
            bs.place_order(self.viewer, big_session, seat_ids[:ticket_limit() + 1], CARD)
        self.assertEqual(self.count("orders"), 0)
        self.assertEqual(len(bs.place_order(self.viewer, big_session, seat_ids[:ticket_limit()], CARD)["tickets"]), 10)

    def test_cashier_sees_buyer_order_in_shared_data(self):
        self.order((2,))
        cs.open_shift(self.cashier)
        found = cs.search_tickets(self.cashier, client="Пётр")
        self.assertEqual(len(found), 1)
        with self.assertRaises(ValidationError):
            cs.sell(self.cashier, self.session_id, [self.seat_ids[2]], "cash")     # место занято покупателем
        tid = found[0]["id"]
        cs.refund(self.cashier, tid)                                    # касса возвращает билет покупателя
        self.assertEqual(bs.my_tickets(self.viewer, "returned")[0]["id"], tid)
        self.assertEqual(bs.list_my_orders(self.viewer)[0]["status"], "returned")
        cs.sell(self.cashier, self.session_id, [self.seat_ids[2]], "cash")      # место снова свободно


def ticket_limit():
    return tickets.MAX_SEATS_PER_PURCHASE


class BuyerTicketsTests(BuyerBase):
    def test_groups_and_privacy(self):
        mine = self.order((0, 1))["tickets"]
        other = self.order((2,), self.viewer2)["tickets"][0]
        self.assertEqual({t["id"] for t in bs.my_tickets(self.viewer)}, {t["id"] for t in mine})
        self.assertEqual([t["group"] for t in bs.my_tickets(self.viewer, "upcoming")], ["upcoming"] * 2)
        bs.refund(self.viewer, mine[0]["id"])
        self.assertEqual(len(bs.my_tickets(self.viewer, "returned")), 1)
        with patch("services.clock.now", return_value=AFTER_START):
            self.assertEqual(len(bs.my_tickets(self.viewer, "past")), 1)
            self.assertEqual(bs.my_tickets(self.viewer, "upcoming"), [])
        with self.assertRaises(PermissionDenied):
            bs.refund_check(self.viewer, other["id"])
        with self.assertRaises(ValidationError):
            bs.my_tickets(self.viewer, "unknown")

    def test_refund_rules(self):
        t1, t2 = self.order((0, 1))["tickets"]
        other = self.order((2,), self.viewer2)["tickets"][0]
        with self.assertRaises(PermissionDenied):
            bs.refund(self.viewer, other["id"])                         # чужой билет
        self.assertEqual(self.rows("SELECT status FROM tickets WHERE id = ?", other["id"])[0]["status"], "sold")
        self.assertTrue(bs.refund_check(self.viewer, t1["id"])["can_refund"])
        done = bs.refund(self.viewer, t1["id"])
        self.assertEqual(done["status"], "returned")
        row = self.rows("SELECT refunded_by, order_id FROM tickets WHERE id = ?", t1["id"])[0]
        self.assertEqual((row["refunded_by"], row["order_id"] is not None), (self.viewer.id, True))
        self.assertFalse(bs.refund_check(self.viewer, t1["id"])["can_refund"])
        with self.assertRaises(ValidationError):
            bs.refund(self.viewer, t1["id"])                            # повторный возврат
        with self.assertRaises(ValidationError):
            bs.refund(self.viewer, 99999)
        with patch("services.clock.now", return_value=AFTER_START):
            self.assertFalse(bs.refund_check(self.viewer, t2["id"])["can_refund"])
            with self.assertRaises(ValidationError):
                bs.refund(self.viewer, t2["id"])
        self.assertEqual(self.count("orders"), 2)                       # история покупки сохраняется
        self.sell(0, actor=self.cashier)                                 # возвращённое место можно продать снова

    def test_eticket_html(self):
        t = self.order()["tickets"][0]
        t["poster_path"] = None
        html = eticket.eticket_html([t])
        for part in ("AVENOR", "Дюна", f"№ {t['id']}", "Код проверки"):
            self.assertIn(part, html)
        returned = dict(bs.refund(self.viewer, t["id"]), poster_path=None)
        self.assertIn("ВОЗВРАЩЁН", eticket.eticket_html([returned]))
        with self.assertRaises(ValidationError):
            eticket.eticket_html([])
        path = Path(tempfile.mkdtemp()) / "t.html"
        eticket.save_eticket_html(path, [t])
        self.assertIn("AVENOR", path.read_text(encoding="utf-8"))

    def test_poster_is_embedded(self):
        png = Path(tempfile.mkdtemp()) / "p.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
        t = self.order()["tickets"][0]
        with patch("services.movie_service.poster_file", return_value=png):
            self.assertIn("data:image/png;base64,", eticket.eticket_html([dict(t, poster_path="p.png")]))


class BuyerOrdersTests(BuyerBase):
    def test_history_filters_and_privacy(self):
        o1 = self.order((0, 1))
        o2 = self.order((2,))
        self.order((3,), self.viewer2)
        orders = bs.list_my_orders(self.viewer)
        self.assertEqual([o["id"] for o in orders], [o2["order_id"], o1["order_id"]])
        self.assertEqual(orders[1]["tickets_total"], 2)
        self.assertEqual(orders[0]["payment_title"], bs.PAYMENT_TITLE)
        self.assertEqual([o["id"] for o in bs.list_my_orders(self.viewer, order_id=o1["order_id"])], [o1["order_id"]])
        self.assertEqual(bs.list_my_orders(self.viewer, order_id=self.order((4,), self.viewer2)["order_id"]), [])
        today = "16.10.2026"
        self.assertEqual(len(bs.list_my_orders(self.viewer, date_from=today, date_to=today)), 2)
        self.assertEqual(bs.list_my_orders(self.viewer, date_from="17.10.2026"), [])
        bs.refund(self.viewer, o1["tickets"][0]["id"])
        self.assertEqual([o["id"] for o in bs.list_my_orders(self.viewer, status="partial")], [o1["order_id"]])
        bs.refund(self.viewer, o2["tickets"][0]["id"])
        self.assertEqual([o["id"] for o in bs.list_my_orders(self.viewer, status="returned")], [o2["order_id"]])
        for bad in ({"order_id": "abc"}, {"date_from": "xx"}, {"status": "zzz"},
                    {"date_from": "20.10.2026", "date_to": "01.10.2026"}):
            with self.assertRaises(ValidationError):
                bs.list_my_orders(self.viewer, **bad)

    def test_order_tickets_only_own(self):
        mine, theirs = self.order((0, 1)), self.order((2,), self.viewer2)
        self.assertEqual(len(bs.get_order_tickets(self.viewer, mine["order_id"])), 2)
        with self.assertRaises(PermissionDenied):
            bs.get_order_tickets(self.viewer, theirs["order_id"])
        with self.assertRaises(ValidationError):
            bs.get_order_tickets(self.viewer, 99999)

    def test_legacy_buyer_tickets_are_backfilled(self):
        tickets.sell_ticket(self.viewer, self.session_id, self.seat_ids[0], self.viewer.client_id)   # старый путь, без заказа
        self.assertEqual(self.count("orders"), 0)
        conn = get_connection(self.db)
        conn.execute("DROP TABLE orders")                                # имитируем базу до появления заказов
        conn.execute("DROP INDEX IF EXISTS ix_orders_user")
        conn.commit()
        schema.create_schema(conn)
        order = conn.execute("SELECT o.* FROM orders o JOIN tickets t ON t.order_id = o.id").fetchone()
        conn.close()
        self.assertEqual((order["user_id"], order["payment_method"], order["total"]), (self.viewer.id, None, 300))
        self.assertEqual(bs.list_my_orders(self.viewer)[0]["payment_title"], "Не указан")


class BuyerProfileTests(BuyerBase):
    def test_profile_update(self):
        p = bs.get_profile(self.viewer)
        self.assertEqual((p["username"], p["full_name"], p["phone"]), ("view", "Покупатель Пётр", None))
        self.assertTrue(p["created_at"])                                  # дата регистрации ставится при создании
        new = bs.update_profile(self.viewer, "Пётр  Иванов", "8 (999) 111-22-33", "Petr@Mail.ru")
        self.assertEqual((new["full_name"], new["phone"], new["email"]), ("Пётр Иванов", "+79991112233", "petr@mail.ru"))
        self.assertEqual(self.rows("SELECT full_name FROM users WHERE id = ?", self.viewer.id)[0][0], "Пётр Иванов")
        self.assertEqual(bs.get_profile(self.viewer)["full_name"], "Пётр Иванов")

    def test_profile_validation_and_isolation(self):
        bs.update_profile(self.viewer, "Пётр", "+79991112233", "p@mail.ru")
        for args in (("", None, None), ("Пётр", "123", None), ("Пётр", None, "не-почта"), ("x" * 200, None, None)):
            with self.assertRaises(ValidationError):
                bs.update_profile(self.viewer, *args)
        with self.assertRaises(ValidationError):
            bs.update_profile(self.viewer2, "Ольга", "+79991112233", None)     # телефон другого покупателя
        with self.assertRaises(ValidationError):
            bs.update_profile(self.viewer2, "Ольга", None, "P@mail.ru")
        self.assertEqual(bs.get_profile(self.viewer2)["phone"], None)
        self.assertEqual(self.rows("SELECT full_name FROM users WHERE id = ?", self.viewer2.id)[0][0], "Покупатель Ольга")

    def test_password_change_and_storage(self):
        auth.change_own_password(self.viewer, "secret1", "newpass1")
        self.assertEqual(auth.login("view", "newpass1").id, self.viewer.id)
        with self.assertRaises(Exception):
            auth.login("view", "secret1")
        stored = self.rows("SELECT password_hash FROM users WHERE id = ?", self.viewer.id)[0][0]
        self.assertNotIn("newpass1", stored)

    def test_registration_date_for_all_new_accounts(self):
        self.assertTrue(all(r["created_at"] for r in self.rows("SELECT created_at FROM users")))


class BuyerScreenTests(BuyerBase):
    def film(self):
        frame = gui["buyer_film_frame"].BuyerFilmFrame(fake_tk.Widget(), self.viewer, self.movie_id, "2026-10-17")
        self.addCleanup(frame.destroy)
        return frame

    def seat(self, frame, index):
        return next(s for r in frame._seat_data["rows"] for s in r["seats"] if s["id"] == self.seat_ids[index])

    def test_home_and_poster(self):
        self.sell(0)
        home = gui["buyer_home_frame"].BuyerHomeFrame(fake_tk.Widget(), self.viewer)
        self.assertIn("Покупатель Пётр", home.hello_var.get())
        self.assertEqual(home.wall.card_count(), 3)                        # один фильм: «в афише», «популярное», «новинки»
        poster = gui["buyer_poster_frame"].BuyerPosterFrame(fake_tk.Widget(), self.viewer)
        self.assertEqual(poster.wall.card_count(), 1)
        poster.search_var.set("нет такого")
        poster.refresh()
        self.assertEqual((poster.wall.card_count(), poster.info_var.get()), (0, "Найдено фильмов: 0"))
        poster.reset()
        self.assertEqual(poster.wall.card_count(), 1)

    def test_film_page_full_purchase(self):
        frame = self.film()
        self.assertEqual(frame._session_id, self.session_id)
        frame._on_seat_click(self.seat(frame, 0))
        frame._on_seat_click(self.seat(frame, 1))
        self.assertIn("600", frame.total_var.get().replace("\xa0", "").replace(" ", ""))
        frame._on_seat_click(self.seat(frame, 1))                           # снятие выбора пересчитывает цену
        self.assertIn("300", frame.total_var.get().replace("\xa0", "").replace(" ", ""))
        frame._on_seat_click(self.seat(frame, 1))
        frame._to_checkout()
        dialog = self.last(gui["buyer_dialogs"].CheckoutDialog)
        dialog.vars["number"].set("1111")                                   # неверная карта: окно остаётся, заказа нет
        dialog.confirm()
        self.assertTrue(dialog.error_var.get())
        self.assertEqual(self.count("orders"), 0)
        for key, value in CARD.items():
            dialog.vars[key].set(value)
        dialog.confirm()
        self.assertEqual((self.count("orders"), self.count("tickets")), (1, 2))
        self.assertTrue(any(isinstance(w, gui["buyer_dialogs"].ETicketDialog) for w in fake_tk.CREATED))
        self.assertTrue(self.messages("info"))

    def test_seat_taken_elsewhere_is_reported(self):
        frame = self.film()
        frame._on_seat_click(self.seat(frame, 0))
        self.sell(0, actor=self.cashier)
        frame._to_checkout()
        self.assertEqual(self.count("orders"), 0)
        self.assertTrue(self.messages("warning"))
        self.assertNotIn(self.seat_ids[0], frame._selected)

    def test_client_less_buyer_cannot_checkout(self):
        guest = dataclasses.replace(self.viewer, client_id=None)
        frame = gui["buyer_film_frame"].BuyerFilmFrame(fake_tk.Widget(), guest, self.movie_id, "2026-10-17")
        frame._on_seat_click(self.seat(frame, 0))
        frame._to_checkout()
        self.assertIn("не привязана", frame.error_var.get())
        self.assertEqual(self.count("orders"), 0)

    def test_tickets_screen_refund(self):
        t = self.order((0, 1))["tickets"][0]
        frame = gui["buyer_tickets_frame"].BuyerTicketsFrame(fake_tk.Widget(), self.viewer)
        self.assertEqual(len(frame._tickets), 2)
        frame.select(t["id"])
        frame.show_ticket()
        self.assertTrue(any(isinstance(w, gui["buyer_dialogs"].ETicketDialog) for w in fake_tk.CREATED))
        with patch.object(gui["buyer_tickets_frame"], "ask_confirm", return_value=True):
            frame.refund()
        self.assertEqual(self.rows("SELECT status FROM tickets WHERE id = ?", t["id"])[0][0], "returned")
        self.assertEqual(len(frame._tickets), 1)
        frame.set_group("returned")
        self.assertEqual([x["id"] for x in frame._tickets], [t["id"]])
        frame.select(t["id"])
        with patch.object(gui["buyer_tickets_frame"], "ask_confirm", return_value=True):
            frame.refund()                                                   # возвращённый билет повторно не вернуть
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tickets WHERE status = 'returned'")[0][0], 1)

    def test_orders_screen_and_profile_screen(self):
        o = self.order((0, 1))
        self.order((2,), self.viewer2)
        frame = gui["buyer_orders_frame"].BuyerOrdersFrame(fake_tk.Widget(), self.viewer)
        self.assertEqual(list(frame._orders), [o["order_id"]])
        frame.id_var.set("abc")
        frame.search()
        self.assertTrue(self.messages("error") or self.messages("warning"))   # неверный номер заказа — понятное сообщение
        frame.reset()
        self.select(frame.table, o["order_id"])
        frame._on_select()
        frame._show_tickets()
        self.assertTrue(any(isinstance(w, gui["buyer_dialogs"].ETicketDialog) for w in fake_tk.CREATED))
        profile = gui["buyer_profile_frame"].BuyerProfileFrame(fake_tk.Widget(), self.viewer)
        profile.vars["full_name"].set("Пётр Новый")
        profile.vars["phone"].set("+79990001122")
        profile.save()
        self.assertEqual(bs.get_profile(self.viewer)["full_name"], "Пётр Новый")
        profile.vars["phone"].set("абв")                      # буквы в поле телефона отбрасываются при вводе
        self.assertEqual(profile.vars["phone"].get(), "")
        profile.vars["phone"].set("+7 916")                   # неполный номер сервис отклоняет, прежний остаётся
        profile.save()
        self.assertEqual(bs.get_profile(self.viewer)["phone"], "+79990001122")

    def test_main_frame_routing(self):
        main = gui["main_frame"].MainFrame(fake_tk.Widget(), self.viewer, on_logout=lambda: None)
        self.assertIsInstance(main.content.winfo_children()[0], gui["buyer_home_frame"].BuyerHomeFrame)
        main.open_screen("poster")
        main.content.winfo_children()[0].open_movie(self.movie_id)
        self.assertIsInstance(main.content.winfo_children()[0], gui["buyer_film_frame"].BuyerFilmFrame)
        main.open_screen("profile")
        self.assertIsNotNone(main.content.winfo_children()[0].logout)
        for forbidden in ("sale", "refund", "shift", "cash_home", "reports", "users", "schedule", "tickets"):
            before = main.content.winfo_children()[0]
            main.open_screen(forbidden)
            self.assertIs(main.content.winfo_children()[0], before, forbidden)

    def test_other_roles_do_not_get_buyer_screens(self):
        for user, keys in ((self.admin, ("buyer_home", "poster", "orders", "profile")),
                           (self.cashier, ("buyer_home", "poster", "orders", "profile", "my_tickets"))):
            main = gui["main_frame"].MainFrame(fake_tk.Widget(), user, on_logout=lambda: None)
            before = main.content.winfo_children()[0]
            for key in keys:
                main.open_screen(key)
                self.assertIs(main.content.winfo_children()[0], before, key)
        admin_main = gui["main_frame"].MainFrame(fake_tk.Widget(), self.admin, on_logout=lambda: None)
        self.assertNotIn("schedule", admin_main.menu_buttons)      # у администратора нет афиши с продажей билетов
        admin_main.open_screen("schedule")
        self.assertIsInstance(admin_main.content.winfo_children()[0], gui["dashboard_frame"].DashboardFrame)


class UnchangedBehaviourTests(BuyerBase):
    """Админ и касса работают по-прежнему: общий код расширен только необязательными параметрами."""

    def test_admin_and_cashier_paths(self):
        with self.assertRaises(PermissionDenied):
            tickets.sell_ticket(self.admin, self.session_id, self.seat_ids[4], {"full_name": "Клиент"})
        t = tickets.sell_ticket(self.cashier, self.session_id, self.seat_ids[4], {"full_name": "Клиент"})
        self.assertEqual(self.rows("SELECT order_id, sale_id FROM tickets WHERE id = ?", t["id"])[0][:], (None, None))
        self.assertEqual(tickets.refund_ticket(self.admin, t["id"])["status"], "returned")
        with self.assertRaises(ValidationError):
            tickets.refund_ticket(self.admin, t["id"])
        with self.assertRaises(PermissionDenied):
            tickets.sell_tickets(self.cashier, self.session_id, [self.seat_ids[0]], 1, order_info={"payment_method": "card"})
        with self.assertRaises(PermissionDenied):
            tickets.sell_tickets(self.viewer, self.session_id, [self.seat_ids[0]], self.viewer.client_id,
                                 sale_info={"shift_id": 1, "payment_method": "cash"})
        with self.assertRaises(PermissionDenied):
            tickets.refund_own_ticket(self.cashier, t["id"])
        self.assertEqual(self.count("orders"), 0)
        cs.open_shift(self.cashier)
        self.assertEqual(cs.sell(self.cashier, self.session_id, [self.seat_ids[5]], "cash")["total"], 300)


if __name__ == "__main__":
    unittest.main()


class BuyerDayFilterTests(BuyerBase):
    def setUp(self):
        super().setUp()
        self.hall2 = halls.create_hall(self.admin, "Зал 2", 1, 4)
        self.movie2 = movies.create_movie(self.admin, "Ёлки", self.genre_id, 90, "0+")
        sessions.create_session(self.admin, self.movie2, self.hall2, "2026-10-19", "12:00", 200)   # понедельник

    def test_catalog_days_and_filter_by_day(self):
        self.assertEqual(bs.catalog_days(self.viewer), ["2026-10-17", "2026-10-19"])
        self.assertEqual([m["title"] for m in bs.catalog(self.viewer, day="2026-10-17")], ["Дюна"])
        elki = bs.catalog(self.viewer, day="2026-10-19")
        self.assertEqual([(m["title"], m["next_date"], m["min_price"], m["sessions"]) for m in elki],
                         [("Ёлки", "2026-10-19", 200, 1)])
        self.assertEqual(bs.catalog(self.viewer, day="2026-10-25"), [])
        with self.assertRaises(ValidationError):
            bs.catalog(self.viewer, day="не дата")

    def test_day_bar_and_poster_screen(self):
        from gui import formatting
        self.assertEqual(formatting.day_caption("2026-10-17", NOW_DAY), "Завтра")
        frame = gui["buyer_poster_frame"].BuyerPosterFrame(fake_tk.Widget(), self.viewer)
        self.assertEqual(frame.wall.card_count(), 2)
        frame.day_bar.pick("2026-10-19")
        self.assertEqual(frame.wall.card_count(), 1)
        frame.reset()
        self.assertEqual(frame.wall.card_count(), 2)
        frame.set_day("2026-10-17")
        self.assertEqual(frame.wall.card_count(), 1)

    def test_home_day_button_opens_poster_on_that_day(self):
        frame = gui["buyer_home_frame"].BuyerHomeFrame(fake_tk.Widget(), self.viewer)
        calls = []
        frame.navigate = lambda key, **kw: calls.append((key, kw))
        frame.day_bar.pick("2026-10-19")
        frame.day_bar.pick(None)
        self.assertEqual(calls, [("poster", {"day": "2026-10-19"}), ("poster", {})])


from datetime import date as _date          # noqa: E402
NOW_DAY = _date(2026, 10, 16)
