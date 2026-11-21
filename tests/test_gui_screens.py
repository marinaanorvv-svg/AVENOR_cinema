"""Сценарии экранов на заглушке tkinter: продажа, возврат, справочники, сеансы, пользователи, отчёты.

Запуск:  python -m unittest tests.test_gui_screens -v
"""
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from tests import fake_tk
from tests import test_gui_smoke as smoke


def setUpModule():
    smoke.setUpModule()


def tearDownModule():
    smoke.tearDownModule()


from database import crud                                  # noqa: E402
from database.connection import get_connection             # noqa: E402
from services import auth_service as auth                  # noqa: E402
from services import genre_service as genres               # noqa: E402
from services import hall_service as halls                 # noqa: E402
from services import movie_service as movies               # noqa: E402
from services import session_service as sessions           # noqa: E402
from services import ticket_service as tickets             # noqa: E402
from services.errors import ServiceError                   # noqa: E402

gui = smoke.gui


class ScreenBase(smoke.SmokeBase):
    """Общий «мир»: жанр, фильм (155 мин), зал 2×5 и сеанс 17.10.2026 18:00 за 300 ₽."""

    def setUp(self):
        super().setUp()
        self.genre_id = genres.create_genre(self.admin, "Драма")
        self.movie_id = movies.create_movie(self.admin, "Дюна", self.genre_id, 155, "12+")
        self.hall_id = halls.create_hall(self.admin, "Зал 1", 2, 5)
        self.session_id = sessions.create_session(self.admin, self.movie_id, self.hall_id,
                                                  "2026-10-17", "18:00", 300)
        scheme = halls.get_hall_scheme(self.admin, self.hall_id)
        self.seat_ids = [s["id"] for row in scheme["rows"] for s in row["seats"]]

    # --- помощники
    def sell(self, seat_index=0, client=None, actor=None):
        return tickets.sell_ticket(actor or self.cashier, self.session_id, self.seat_ids[seat_index],
                                   client or {"full_name": f"Клиент {seat_index}"})

    def count(self, table):
        conn = get_connection(self.db)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()

    def last(self, cls):
        return [w for w in fake_tk.CREATED if isinstance(w, cls)][-1]

    def dialog(self):
        return self.last(gui["forms"].FormDialog)

    def submit(self, **values):
        dialog = self.dialog()
        for key, value in values.items():
            dialog.set_value(key, value)
        dialog._submit()
        return dialog

    def messages(self, kind):
        return [m for k, _, m in fake_tk.MESSAGEBOX.calls if k == kind]

    @staticmethod
    def select(table, iid):
        table.tree._selection = (str(iid),)


# ------------------------------------------------------------------ универсальные виджеты

class WidgetTests(ScreenBase):
    def test_form_dialog_collects_all_field_kinds(self):
        Field, FormDialog = gui["forms"].Field, gui["forms"].FormDialog
        saved = []
        dialog = FormDialog(fake_tk.Widget(), "Тест", [
            Field("name", "Имя", value="Иван"), Field("pwd", "Пароль", "password"),
            Field("kind", "Тип", "combo", options=((1, "Один"), (2, "Два")), value=2),
            Field("note", "Заметка", "text", value="строка"), Field("path", "Файл", "file")],
            on_submit=lambda v: saved.append(v), on_saved=lambda: saved.append("saved"))
        self.assertEqual(dialog.get_values(), {"name": "Иван", "pwd": "", "kind": 2, "note": "строка", "path": ""})
        dialog.set_value("kind", 1)
        dialog.set_value("note", "новая")
        fake_tk.FILEDIALOG.result = "/tmp/a.png"
        dialog._browse(dialog.inputs["path"], dialog.fields[4])
        dialog._submit()
        self.assertEqual(saved[0]["kind"], 1)
        self.assertEqual((saved[0]["note"], saved[0]["path"]), ("новая", "/tmp/a.png"))
        self.assertEqual(saved[1], "saved")
        self.assertTrue(dialog._destroyed)

    def test_form_dialog_keeps_open_on_service_error_and_reports_bugs(self):
        Field, FormDialog = gui["forms"].Field, gui["forms"].FormDialog

        def reject(values):
            raise ServiceError("Неверные данные")

        dialog = FormDialog(fake_tk.Widget(), "Тест", [Field("a", "A")], on_submit=reject)
        dialog._submit()
        self.assertEqual(dialog.error_var.get(), "Неверные данные")
        self.assertFalse(dialog._destroyed)

        def crash(values):
            raise RuntimeError("boom")

        dialog = FormDialog(fake_tk.Widget(), "Тест", [Field("a", "A")], on_submit=crash)
        with self.assertLogs("cinema", "ERROR"):
            dialog._submit()
        self.assertEqual(fake_tk.MESSAGEBOX.calls[-1][0], "error")

    def test_combo_value_mapping_and_option_refresh(self):
        combo = gui["widgets"].Combo(fake_tk.Widget(), [(None, "Все"), (7, "Семь")])
        combo.set_value(7)
        self.assertEqual(combo.value(), 7)
        combo.set_options([(None, "Все"), (7, "Семь"), (8, "Восемь")])
        self.assertEqual(combo.value(), 7)                        # выбор сохранился
        combo.set_options([(None, "Все")])
        self.assertIsNone(combo.value())
        self.assertEqual(combo.get(), "Все")

    def test_seat_states_and_rendering(self):
        seat_state = gui["seat_map"].seat_state
        self.assertEqual(seat_state({"id": 1, "seat_type": "regular"}), "free")
        self.assertEqual(seat_state({"id": 1, "seat_type": "vip"}), "vip")
        self.assertEqual(seat_state({"id": 1, "seat_type": "vip"}, {1}), "selected")
        self.assertEqual(seat_state({"id": 1, "seat_type": "vip", "is_sold": True}, {1}), "sold")
        clicked = []
        seat_map = gui["seat_map"].SeatMap(fake_tk.Widget(), on_click=clicked.append)
        rows = halls.get_hall_scheme(self.admin, self.hall_id)["rows"]
        seat_map.render(rows)
        self.assertEqual(len(seat_map.seat_items), 10)                                # кресло нарисовано для каждого места
        self.assertEqual(sorted(seat_map.seat_items), sorted(s["id"] for r in rows for s in r["seats"]))
        seat_map.render(rows, selected={rows[0]["seats"][0]["id"]})                   # повторная отрисовка начинается с чистого холста
        self.assertEqual(len(seat_map.seat_items), 10)
        seat_map._clicked(rows[0]["seats"][0])
        self.assertEqual(clicked[0]["seat_number"], 1)


# ------------------------------------------------------------------ продажа

class FilmFrameTests(ScreenBase):
    """Страница фильма: день -> время -> кресла -> покупка. Других фильмов на экране нет."""

    def make(self, user=None, date="2026-10-17"):
        return gui["film_frame"].FilmFrame(fake_tk.Widget(), user or self.cashier, self.movie_id, date)

    @staticmethod
    def seats(frame):
        return [s for row in frame._seat_data["rows"] for s in row["seats"]]

    def test_shows_only_chosen_movie_and_opens_first_session(self):
        other = movies.create_movie(self.admin, "Чужой фильм", self.genre_id, 90, "6+")
        sessions.create_session(self.admin, other, self.hall_id, "2026-10-17", "10:00", 200)
        frame = self.make()
        self.assertEqual(frame.title_label.cget("text"), "Дюна")
        self.assertEqual(frame._session_id, self.session_id)
        self.assertEqual([s["id"] for s in frame._days["2026-10-17"]], [self.session_id])   # сеанса чужого фильма нет
        self.assertEqual(len(self.seats(frame)), 10)
        self.assertIn("Зал 1", frame.info_var.get())
        self.assertIn("до 20:35", frame.info_var.get())                                      # 18:00 + 155 мин
        self.assertFalse(frame.buy_button.enabled)                                           # места не выбраны

    def test_days_and_times_switch_session(self):
        late = sessions.create_session(self.admin, self.movie_id, self.hall_id, "2026-10-18", "10:00", 250)
        frame = self.make()
        self.assertEqual(list(frame._days), ["2026-10-17", "2026-10-18"])
        frame._shift_day(1)                                          # стрелка ▶ листает на следующий день с сеансами
        self.assertEqual((frame._day, frame._session_id), ("2026-10-18", late))
        frame._shift_day(1)                                          # дальше по кругу — снова первый день
        self.assertEqual(frame._day, "2026-10-17")
        frame._select_day("2026-10-18")
        self.assertEqual(frame._session_id, late)
        self.assertIn("250", frame.info_var.get())
        frame._open_session(late)
        self.assertEqual(len(frame.times_row.winfo_children()), 1)

    def test_past_sessions_and_other_dates_are_not_offered(self):
        sessions.create_session(self.admin, self.movie_id, self.hall_id, "2026-10-16", "13:00", 300)
        with patch("services.clock.now", return_value=datetime(2026, 10, 16, 14, 0)), \
                patch("services.session_service._now", return_value=datetime(2026, 10, 16, 14, 0)):
            frame = self.make(date="2026-10-16")
        self.assertEqual(list(frame._days), ["2026-10-17"])           # сеанс в 13:00 уже начался
        self.assertEqual(frame._day, "2026-10-17")

    def test_movie_without_sessions(self):
        lonely = movies.create_movie(self.admin, "Без сеансов", self.genre_id, 90, "6+")
        frame = gui["film_frame"].FilmFrame(fake_tk.Widget(), self.cashier, lonely)
        self.assertIn("нет сеансов", frame.info_var.get())
        self.assertFalse(frame.buy_button.enabled)

    def test_select_and_unselect_seats_updates_summary(self):
        frame = self.make()
        a, b = self.seats(frame)[:2]
        frame._on_seat_click(a)
        frame._on_seat_click(b)
        self.assertEqual(frame._selected, {a["id"], b["id"]})
        self.assertEqual(frame.selection_var.get(), "Ряд 1, места 1 и 2")
        self.assertIn("600", frame.total_var.get())                 # «Итого 600 ₽» над кнопкой
        self.assertTrue(frame.buy_button.enabled)
        frame._on_seat_click(a)
        self.assertEqual(frame._selected, {b["id"]})
        frame._on_seat_click(b)
        self.assertFalse(frame.buy_button.enabled)

    def test_sold_seat_cannot_be_selected_and_limit_is_enforced(self):
        self.sell(0)
        frame = self.make()
        sold, *free = self.seats(frame)
        self.assertTrue(sold["is_sold"])
        frame._on_seat_click(sold)
        self.assertEqual(frame._selected, set())
        with patch("services.ticket_service.MAX_SEATS_PER_PURCHASE", 2):
            for seat in free[:3]:
                frame._on_seat_click(seat)
        self.assertEqual(len(frame._selected), 2)
        self.assertIn("не более 2", frame.error_var.get())

    def test_buyer_flow_buys_for_himself(self):
        frame = self.make(user=self.viewer)
        self.assertTrue(frame.self_service)
        for seat in self.seats(frame)[:2]:
            frame._on_seat_click(seat)
        frame._buy()
        kind, title, text = fake_tk.MESSAGEBOX.calls[-1]
        self.assertEqual((kind, title), ("info", "Билеты оформлены"))
        self.assertIn("Покупатель Пётр", text)
        self.assertEqual(self.count("tickets"), 2)
        self.assertEqual(sum(s["is_sold"] for s in self.seats(frame)), 2)

    def test_account_without_client_cannot_buy(self):
        frame = self.make(user=self.viewer)
        frame.can_buy = False                    # учётная запись не привязана к покупателю
        frame._on_seat_click(self.seats(frame)[0])
        self.assertEqual(frame._selected, set())
        self.assertIn("не привязана", frame.error_var.get())

    def test_sale_flow_shows_receipt_and_refreshes(self):
        frame = self.make()
        for seat in self.seats(frame)[:2]:
            frame._on_seat_click(seat)
        frame.name_var.set("Иван Иванов")
        frame.phone_var.set("8 999 123 45 67")
        frame._buy()
        kind, title, text = fake_tk.MESSAGEBOX.calls[-1]
        self.assertEqual((kind, title), ("info", "Билеты оформлены"))
        self.assertIn("Итого: 600", text)
        self.assertIn("Иван Иванов", text)
        self.assertEqual(self.count("tickets"), 2)
        self.assertEqual((frame.name_var.get(), frame._selected), ("", set()))   # форма очищена
        self.assertEqual(sum(s["is_sold"] for s in self.seats(frame)), 2)         # схема перерисована

    def test_missing_client_name_keeps_selection(self):
        frame = self.make()
        seat = self.seats(frame)[0]
        frame._on_seat_click(seat)
        frame._buy()
        self.assertIn("ФИО", self.messages("warning")[-1])
        self.assertEqual(frame._selected, {seat["id"]})
        self.assertEqual(self.count("tickets"), 0)

    def test_seat_sold_by_another_cashier_meanwhile(self):
        frame = self.make()
        a, b = self.seats(frame)[:2]
        frame._on_seat_click(a)
        frame._on_seat_click(b)
        tickets.sell_ticket(self.cashier, self.session_id, b["id"], {"full_name": "Другой кассир"})
        frame.name_var.set("Иван")
        frame._buy()
        self.assertIn("занято", self.messages("warning")[-1])
        self.assertEqual(self.count("tickets"), 1)                 # ничего лишнего не продано
        self.assertEqual(frame._selected, {a["id"]})               # занятое место снято с выбора
        self.assertTrue(next(s for s in self.seats(frame) if s["id"] == b["id"])["is_sold"])

    def test_pick_existing_client_reuses_record(self):
        self.sell(0, {"full_name": "Анна Смирнова", "phone": "+7 999 000 11 22"})
        clients_before = self.count("clients")
        frame = self.make()
        frame._on_seat_click(self.seats(frame)[1])
        frame._pick_client()
        dialog = self.last(gui["film_frame"].ClientSearchDialog)
        dialog.query_var.set("СМИРН")
        dialog.search()
        self.assertEqual(len(dialog.table.tree.rows), 1)
        self.select(dialog.table, next(iter(dialog.table.tree.rows)))
        dialog._choose()
        self.assertEqual((frame.name_var.get(), frame.phone_var.get()), ("Анна Смирнова", "+7 999 000-11-22"))
        frame._buy()
        self.assertEqual(self.count("clients"), clients_before)    # новый клиент не создан
        self.assertEqual(self.count("tickets"), 2)

    def test_back_button_calls_callback(self):
        calls = []
        frame = gui["film_frame"].FilmFrame(fake_tk.Widget(), self.cashier, self.movie_id, None, on_back=lambda: calls.append(1))
        frame._back()
        self.assertEqual(calls, [1])


# ------------------------------------------------------------------ билеты

class TicketsScreenTests(ScreenBase):
    def setUp(self):
        super().setUp()
        self.t1 = self.sell(0, {"full_name": "Иван Иванов"})
        self.t2 = self.sell(1, {"full_name": "Анна Петрова", "phone": "89991234567"})

    def make(self, user=None):
        return gui["tickets_frame"].TicketsFrame(fake_tk.Widget(), user or self.cashier)

    def test_search_filters_and_reset(self):
        frame = self.make()
        self.assertEqual(len(frame.table.tree.rows), 2)
        self.assertIn("2", frame.info_var.get())
        frame.client_var.set("ПЕТРОВ")
        frame.search()
        self.assertEqual(list(frame.table.tree.rows), [str(self.t2["id"])])
        frame._reset_filters()
        self.assertEqual(len(frame.table.tree.rows), 2)
        frame.id_var.set(str(self.t1["id"]))
        frame.search()
        self.assertEqual(list(frame.table.tree.rows), [str(self.t1["id"])])
        frame.id_var.set("abc")
        frame.search()
        self.assertTrue(self.messages("warning"))                  # неверный номер -> понятное предупреждение

    def test_refund_flow(self):
        frame = self.make()
        self.select(frame.table, self.t1["id"])
        frame._on_select()
        self.assertEqual(frame.refund_button.cget("state"), "normal")
        fake_tk.MESSAGEBOX.answer = False                           # отказ в подтверждении
        frame._refund()
        self.assertEqual(tickets.get_ticket(self.cashier, self.t1["id"])["status"], "sold")
        fake_tk.MESSAGEBOX.answer = True
        frame._refund()
        self.assertEqual(tickets.get_ticket(self.cashier, self.t1["id"])["status"], "returned")
        self.assertIn("возвращён", self.messages("info")[-1])
        self.assertEqual(frame.table.tree.rows[str(self.t1["id"])]["values"][8], "Возвращён")
        frame._on_select()
        self.assertEqual(frame.refund_button.cget("state"), "disabled")

    def test_refund_disabled_after_session_start(self):
        with patch("services.clock.now", return_value=datetime(2026, 10, 17, 18, 30)):
            frame = self.make()
            self.select(frame.table, self.t1["id"])
            frame._on_select()
            self.assertEqual(frame.refund_button.cget("state"), "disabled")
            frame._refund()                                          # даже при принудительном вызове сервис откажет
            self.assertIn("начался", self.messages("warning")[-1])

    def test_refund_without_selection(self):
        frame = self.make()
        frame._refund()
        self.assertIn("Выберите билет", self.messages("info")[-1])

    def test_my_tickets_shows_only_own(self):
        mine = self.sell(2, self.viewer.client_id)
        frame = gui["tickets_frame"].MyTicketsFrame(fake_tk.Widget(), self.viewer)
        self.assertEqual(list(frame.table.tree.rows), [str(mine["id"])])
        self.assertEqual(len(frame.table.tree.rows[str(mine["id"])]["values"]), 8)
        self.assertIn("1", frame.info_var.get())


# ------------------------------------------------------------------ справочники

class MoviesScreenTests(ScreenBase):
    def make(self):
        return gui["movies_frame"].MoviesFrame(fake_tk.Widget(), self.admin)

    def test_genre_crud(self):
        frame = self.make()
        frame._add_genre()
        self.submit(name="Комедия")
        self.assertEqual(len(frame.genre_table.tree.rows), 2)
        frame._add_genre()
        dialog = self.submit(name="комедия")                       # дубликат без учёта регистра
        self.assertIn("уже существует", dialog.error_var.get())
        self.assertFalse(dialog._destroyed)
        new_id = next(g["id"] for g in genres.list_genres(self.admin) if g["name"] == "Комедия")
        self.select(frame.genre_table, new_id)
        frame._rename_genre()
        self.submit(name="Юмор")
        self.assertEqual(frame.genre_table.tree.rows[str(new_id)]["values"][0], "Юмор")
        frame._delete_genre()
        self.assertNotIn(str(new_id), frame.genre_table.tree.rows)
        self.select(frame.genre_table, self.genre_id)               # жанр используется фильмом
        frame._delete_genre()
        self.assertIn("указан у фильмов", self.messages("warning")[-1])

    def test_movie_add_edit_delete_and_search(self):
        frame = self.make()
        frame._add_movie()
        dialog = self.submit(title="Аватар", genre_id=self.genre_id, duration="162", age_rating="12+",
                             description="Описание")
        self.assertTrue(dialog._destroyed)
        self.assertEqual(len(frame.movie_table.tree.rows), 2)
        new_id = next(m["id"] for m in movies.list_movies(self.admin) if m["title"] == "Аватар")
        self.assertEqual(frame.movie_table.tree.rows[str(new_id)]["values"][2], "2 ч 42 мин")

        self.select(frame.movie_table, new_id)
        frame._edit_movie()
        self.assertEqual(self.dialog().get_values()["title"], "Аватар")       # форма предзаполнена
        self.submit(title="Аватар 2", duration="0")
        self.assertTrue(self.dialog().error_var.get())                        # неверная длительность — ошибка в форме
        self.submit(duration="180")
        self.assertEqual(frame.movie_table.tree.rows[str(new_id)]["values"][0], "Аватар 2")

        frame.search_var.set("ДЮН")
        frame.reload_movies()
        self.assertEqual(list(frame.movie_table.tree.rows), [str(self.movie_id)])
        frame.search_var.set("")
        frame.reload_movies()
        self.select(frame.movie_table, new_id)
        frame._delete_movie()
        self.assertNotIn(str(new_id), frame.movie_table.tree.rows)
        self.select(frame.movie_table, self.movie_id)                         # у «Дюны» есть сеанс
        frame._delete_movie()
        self.assertIn("сеансы", self.messages("warning")[-1])

    def test_add_movie_without_genres(self):
        with patch("services.admin_service.list_genres_with_counts", return_value=[]):
            frame = self.make()
        frame._add_movie()
        self.assertIn("добавьте хотя бы один жанр", self.messages("info")[-1])

    def test_edit_without_selection_gives_hint(self):
        frame = self.make()
        frame._edit_movie()
        self.assertIn("Выберите фильм", self.messages("info")[-1])


class HallsScreenTests(ScreenBase):
    def make(self):
        return gui["halls_frame"].HallsFrame(fake_tk.Widget(), self.admin)

    def test_create_and_show_scheme(self):
        frame = self.make()
        frame._create_hall()
        self.submit(name="Зал VIP", rows="3", seats_per_row="4", vip_rows="3")
        new_id = next(h["id"] for h in halls.list_halls(self.admin) if h["name"] == "Зал VIP")
        self.assertEqual(frame.table.tree.rows[str(new_id)]["values"], ("Зал VIP", 12))
        self.select(frame.table, new_id)
        frame._on_select()
        self.assertIn("3 рядов × 4 мест", frame.title_var.get())

    def test_invalid_layout_keeps_dialog_open(self):
        frame = self.make()
        frame._create_hall()
        dialog = self.submit(name="Плохой", rows="0", seats_per_row="5")
        self.assertTrue(dialog.error_var.get())
        self.assertFalse(dialog._destroyed)

    def test_click_seat_toggles_vip(self):
        frame = self.make()
        self.select(frame.table, self.hall_id)
        frame._on_select()
        seat = frame._scheme["rows"][0]["seats"][0]
        frame._on_seat_click(seat)
        self.assertEqual(frame._scheme["rows"][0]["seats"][0]["seat_type"], "vip")
        frame._on_seat_click(frame._scheme["rows"][0]["seats"][0])
        self.assertEqual(frame._scheme["rows"][0]["seats"][0]["seat_type"], "regular")

    def test_seat_with_tickets_cannot_change_type(self):
        self.sell(0)
        frame = self.make()
        self.select(frame.table, self.hall_id)
        frame._on_select()
        frame._on_seat_click(frame._scheme["rows"][0]["seats"][0])
        self.assertIn("билеты", self.messages("warning")[-1])
        self.assertEqual(frame._scheme["rows"][0]["seats"][0]["seat_type"], "regular")

    def test_reconfigure_prefilled_and_blocked_by_sessions(self):
        hall = halls.create_hall(self.admin, "Пустой", 2, 3, "2")       # без сеансов
        frame = self.make()
        self.select(frame.table, hall)
        frame._on_select()
        frame._reconfigure_hall()
        values = self.dialog().get_values()
        self.assertEqual((values["rows"], values["seats_per_row"], values["vip_rows"]), ("2", "3", "2"))
        self.submit(rows="4", seats_per_row="5", vip_rows="")
        self.assertEqual(frame.table.tree.rows[str(hall)]["values"][1], 20)
        self.select(frame.table, self.hall_id)                          # зал с сеансом
        frame._on_select()
        frame._reconfigure_hall()
        dialog = self.submit(rows="3", seats_per_row="3")
        self.assertIn("есть сеансы", dialog.error_var.get())

    def test_rename_row_type_and_delete(self):
        hall = halls.create_hall(self.admin, "Временный", 2, 2)
        frame = self.make()
        self.select(frame.table, hall)
        frame._on_select()
        frame._rename_hall()
        self.submit(name="Переименованный")
        self.assertEqual(frame.table.tree.rows[str(hall)]["values"][0], "Переименованный")
        frame._set_row_type()
        self.submit(row="2", seat_type="vip")
        self.assertTrue(all(s["seat_type"] == "vip" for s in frame._scheme["rows"][1]["seats"]))
        frame._delete_hall()
        self.assertNotIn(str(hall), frame.table.tree.rows)
        self.assertIn("Выберите", frame.title_var.get())


class SessionsScreenTests(ScreenBase):
    def make(self):
        return gui["sessions_frame"].SessionsFrame(fake_tk.Widget(), self.admin)

    def test_list_shows_sessions_in_period(self):
        frame = self.make()
        values = frame.table.tree.rows[str(self.session_id)]["values"]
        self.assertEqual((values[0], values[2], values[3], values[5]), ("17.10.2026", "Дюна", "Зал 1", "0 из 10"))
        self.assertTrue(values[1].startswith("18:00–20:35"))
        frame.from_var.set("01.01.2030")
        frame.to_var.set("02.01.2030")
        frame.load()
        self.assertEqual(frame.table.tree.rows, {})
        frame.from_var.set("zzz")
        frame.load()
        self.assertTrue(frame.error_var.get())

    def test_add_session_and_validation(self):
        frame = self.make()
        frame._add_session()
        dialog = self.submit(movie_id=self.movie_id, hall_id=self.hall_id, session_date="17.10.2026",
                             session_time="19:00", price="400")        # пересекается с 18:00–20:35
        self.assertIn("Зал занят", dialog.error_var.get())
        self.assertFalse(dialog._destroyed)
        self.submit(session_time="21:00")
        self.assertTrue(self.dialog()._destroyed)
        self.assertEqual(len(frame.table.tree.rows), 2)

    def test_edit_session_prefilled_and_locked_after_sale(self):
        frame = self.make()
        self.select(frame.table, self.session_id)
        frame._edit_session()
        values = self.dialog().get_values()
        self.assertEqual((values["session_date"], values["session_time"], values["price"]),
                         ("17.10.2026", "18:00", "300"))
        self.submit(price="450,5")
        self.assertEqual(sessions.get_session(self.admin, self.session_id)["price"], 450.5)
        self.sell(0)
        frame._edit_session()
        dialog = self.submit(price="500")
        self.assertIn("проданы билеты", dialog.error_var.get())
        self.assertFalse(dialog._destroyed)

    def test_delete_session(self):
        frame = self.make()
        self.select(frame.table, self.session_id)
        self.sell(0)
        frame._delete_session()
        self.assertIn("билеты", self.messages("warning")[-1])
        self.assertIn(str(self.session_id), frame.table.tree.rows)
        free = sessions.create_session(self.admin, self.movie_id, self.hall_id, "2026-10-20", "10:00", 200)
        frame.load()
        self.select(frame.table, free)
        frame._delete_session()
        self.assertNotIn(str(free), frame.table.tree.rows)

    def test_add_requires_movies_and_halls(self):
        frame = self.make()
        with patch("services.movie_service.list_movies", return_value=[]):
            frame._add_session()
        self.assertIn("Сначала добавьте", self.messages("info")[-1])


class UsersScreenTests(ScreenBase):
    def make(self):
        return gui["users_frame"].UsersFrame(fake_tk.Widget(), self.admin)

    def uid(self, username):
        return next(u["id"] for u in auth.list_user_accounts(self.admin) if u["username"] == username)

    def test_list_create_and_validation(self):
        frame = self.make()
        self.assertEqual(len(frame.table.tree.rows), 3)
        frame._create_user()
        dialog = self.submit(username="ab", password="secret1", role="cashier", full_name="Новый")
        self.assertIn("Логин", dialog.error_var.get())
        self.submit(username="kassa2", password="secret1", role="cashier", full_name="Вторая касса")
        self.assertEqual(len(frame.table.tree.rows), 4)
        self.assertEqual(auth.login("kassa2", "secret1").role, "cashier")

    def test_block_unblock_and_button_label(self):
        frame = self.make()
        cash = self.uid("cash")
        self.select(frame.table, cash)
        frame._on_select()
        self.assertEqual(frame.toggle_button.cget("text"), "Заблокировать")
        frame._toggle_user()
        self.assertEqual(frame.table.tree.rows[str(cash)]["values"][3], "Заблокирована")
        self.assertEqual(frame.table.tree.rows[str(cash)]["tags"], ("blocked",))
        self.assertEqual(frame.toggle_button.cget("text"), "Разблокировать")
        frame._toggle_user()
        self.assertEqual(frame.table.tree.rows[str(cash)]["values"][3], "Активна")

    def test_cannot_block_self(self):
        frame = self.make()
        self.select(frame.table, self.admin.id)
        frame._toggle_user()
        self.assertIn("самого себя", self.messages("warning")[-1])

    def test_change_role_and_reset_password(self):
        frame = self.make()
        view = self.uid("view")
        self.select(frame.table, view)
        frame._change_role()
        self.submit(role="cashier")
        self.assertEqual(frame.table.tree.rows[str(view)]["values"][2], "Кассир")
        frame._reset_password()
        dialog = self.submit(password="123")
        self.assertIn("не менее", dialog.error_var.get())
        self.submit(password="brandnew1")
        self.assertEqual(auth.login("view", "brandnew1").role, "cashier")


# ------------------------------------------------------------------ отчёты

class ReportsScreenTests(ScreenBase):
    def setUp(self):
        super().setUp()
        self.sell(0)
        self.sell(1)               # две покупки «сегодня» (16.10.2026), сеанс — 17.10

    def make(self):
        return gui["reports_frame"].ReportsFrame(fake_tk.Widget(), self.admin)

    def test_revenue_report_generated_on_open(self):
        frame = self.make()
        self.assertEqual((frame.from_var.get(), frame.to_var.get()), ("01.10.2026", "16.10.2026"))
        self.assertIn("Продано билетов: 2", frame.summary_var.get())
        self.assertIn("600", frame.summary_var.get())
        rows = frame.table.tree.rows
        self.assertEqual(len(rows), 16 + 1)                                   # 16 дней + «Итого»
        self.assertEqual(rows["totals"]["tags"], ("totals",))
        self.assertEqual(rows["r15"]["values"][0], "16.10.2026")              # даты показаны по-русски
        self.assertEqual(rows["r15"]["values"][1], "2")

    def test_switch_table_and_report_type(self):
        frame = self.make()
        frame.table_combo.set_value("by_movie")
        frame._show_table()
        self.assertEqual(frame.table.tree.rows["r0"]["values"][0], "Дюна")
        frame.type_combo.set_value("attendance")
        frame.to_var.set("31.10.2026")
        frame.upcoming_var.set(True)
        frame.generate()
        self.assertIn("Сеансов: 1", frame.summary_var.get())
        self.assertIn("Зрителей: 2", frame.summary_var.get())
        self.assertIn("20,0", frame.summary_var.get())
        self.assertEqual(frame.table.tree.rows["r0"]["values"][2], "Дюна")

    def test_invalid_period_shows_error(self):
        frame = self.make()
        frame.from_var.set("zzz")
        frame.generate()
        self.assertTrue(frame.error_var.get())
        frame.from_var.set("20.10.2026")
        frame.to_var.set("01.10.2026")
        frame.generate()
        self.assertEqual(frame.error_var.get(), "")                      # старая ошибка очищена
        self.assertIn("позже", self.messages("warning")[-1])             # причина показана предупреждением

    def test_export_csv_and_cancel(self):
        frame = self.make()
        path = os.path.join(self._tmp.name, "out.csv")
        fake_tk.FILEDIALOG.result = ""                                        # пользователь нажал «Отмена»
        frame.export()
        self.assertFalse(os.path.exists(path))
        fake_tk.FILEDIALOG.result = path
        frame.export()
        with open(path, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Итого".encode(), data)
        self.assertIn(path, self.messages("info")[-1])
        fake_tk.FILEDIALOG.result = os.path.join(self._tmp.name, "нет", "out.csv")   # недоступный путь
        frame.export()
        self.assertIn("Не удалось сохранить", self.messages("warning")[-1])


if __name__ == "__main__":
    unittest.main()
