"""Смоук-тест экранов на заглушке tkinter: логика обработчиков + вызовы сервисов.

Запуск:  python -m unittest tests.test_gui_smoke -v
"""
import importlib
import os
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests import fake_tk

_saved = None
gui = {}


def setUpModule():
    global _saved
    _saved = fake_tk.install()
    for name in ("palette", "theme", "neon", "common", "widgets", "forms", "seat_map", "dialogs", "login_frame", "schedule_frame",
                 "film_frame", "tickets_frame", "movies_frame", "halls_frame", "sessions_frame",
                 "users_frame", "reports_frame", "dashboard_frame", "admin_tickets_frame",
                 "cashier_dialogs", "cashier_home_frame", "cashier_sale_frame", "cashier_search_frame",
                 "cashier_refund_frame", "cashier_history_frame", "cashier_shift_frame",
                 "buyer_widgets", "buyer_dialogs", "buyer_home_frame", "buyer_poster_frame", "buyer_film_frame",
                 "buyer_tickets_frame", "buyer_orders_frame", "buyer_profile_frame", "main_frame", "app"):
        gui[name] = importlib.import_module(f"gui.{name}")


def tearDownModule():
    fake_tk.restore(_saved)


from database import crud                              # noqa: E402
from database.connection import transaction            # noqa: E402
from services import auth_service as auth              # noqa: E402
from services import hall_service as halls             # noqa: E402
from services import movie_service as movies           # noqa: E402
from services import genre_service as genres           # noqa: E402
from services import session_service as sessions       # noqa: E402
from services import ticket_service as tickets         # noqa: E402
from services.errors import ServiceError               # noqa: E402
from services.permissions import Role                  # noqa: E402

NOW = datetime(2026, 10, 16, 12, 0)


class SmokeBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "gui.db"
        # GUI вызывает сервисы без db_path -> подменяем путь к БД по умолчанию
        for p in (patch("database.connection.DB_PATH", self.db), patch("services.clock.now", return_value=NOW),
                  patch("services.movie_service.POSTERS_DIR", Path(self._tmp.name) / "posters")):
            p.start()
            self.addCleanup(p.stop)
        auth.ensure_default_admin()
        self.admin = auth.login("admin", "admin123")
        auth.create_user_account(self.admin, "cash", "secret1", Role.CASHIER, "Кассир Анна")
        auth.create_user_account(self.admin, "view", "secret1", Role.VIEWER, "Покупатель Пётр")
        self.cashier, self.viewer = auth.login("cash", "secret1"), auth.login("view", "secret1")
        fake_tk.reset()

    def tearDown(self):
        self._tmp.cleanup()


class LoginFrameTests(SmokeBase):
    def make(self, notice=None):
        self.logged_in = []
        return gui["login_frame"].LoginFrame(fake_tk.Widget(), self.logged_in.append, notice)

    def attempt(self, frame, username, password):
        frame.username_var.set(username)
        frame.password_var.set(password)
        frame._on_login()

    def test_success_calls_callback_and_clears_password(self):
        frame = self.make()
        self.attempt(frame, "cash", "secret1")
        self.assertEqual([u.username for u in self.logged_in], ["cash"])
        self.assertEqual(frame.password_var.get(), "")

    def test_wrong_password_shows_message_and_clears_field(self):
        frame = self.make()
        self.attempt(frame, "cash", "wrong")
        self.assertEqual(self.logged_in, [])
        self.assertIn("Неверный логин или пароль", frame.message_var.get())
        self.assertEqual(frame.password_var.get(), "")

    def test_empty_fields(self):
        frame = self.make()
        self.attempt(frame, "", "")
        self.assertIn("Введите логин и пароль", frame.message_var.get())

    def test_lockout_after_five_failures(self):
        frame = self.make()
        for _ in range(5):
            self.attempt(frame, "cash", "bad")
        self.assertIn("заблокирован", frame.message_var.get())
        self.attempt(frame, "cash", "secret1")         # даже верный пароль в период блокировки не проходит
        self.assertEqual(self.logged_in, [])
        self.assertIn("Слишком много", frame.message_var.get())

    def test_blocked_account_message(self):
        auth.set_user_active(self.admin, self.cashier.id, False)
        frame = self.make()
        self.attempt(frame, "cash", "secret1")
        self.assertIn("заблокирована", frame.message_var.get())

    def test_unexpected_error_goes_to_messagebox_not_crash(self):
        frame = self.make()
        with patch("services.auth_service.login", side_effect=RuntimeError("boom")), \
                self.assertLogs("cinema", "ERROR"):          # ошибка должна попасть в журнал
            self.attempt(frame, "cash", "secret1")
        self.assertEqual(fake_tk.MESSAGEBOX.calls[0][0], "error")
        self.assertEqual(self.logged_in, [])


class MainFrameTests(SmokeBase):
    def make(self, user):
        return gui["main_frame"].MainFrame(fake_tk.Widget(), user, on_logout=lambda: None)

    def test_menu_by_role(self):
        self.assertEqual(list(self.make(self.admin).menu_buttons),
                         ["dashboard", "tickets", "movies", "halls", "sessions", "reports", "users"])
        self.assertEqual(list(self.make(self.cashier).menu_buttons), ["cash_home", "sale", "search", "refund", "history", "shift"])
        self.assertEqual(list(self.make(self.viewer).menu_buttons),
                         ["buyer_home", "poster", "my_tickets", "orders", "profile"])

    def test_every_menu_item_opens_a_real_screen(self):
        for user in (self.admin, self.cashier, self.viewer):
            frame = self.make(user)
            first = {self.admin: gui["dashboard_frame"].DashboardFrame, self.cashier: gui["cashier_home_frame"].CashierHomeFrame,
                     self.viewer: gui["buyer_home_frame"].BuyerHomeFrame}[user]
            self.assertIsInstance(frame.content.winfo_children()[0], first)   # админ начинает с главной панели
            for key in frame.menu_buttons:
                frame.open_screen(key)
                self.assertEqual(len(frame.content.winfo_children()), 1, key)
                self.assertNotIsInstance(frame.content.winfo_children()[0], gui["main_frame"].PlaceholderFrame, key)
        self.assertEqual(fake_tk.MESSAGEBOX.calls, [])   # ни одной ошибки или предупреждения при открытии экранов

    def test_forbidden_screen_is_ignored(self):
        frame = self.make(self.viewer)
        before = frame.content.winfo_children()[0]
        frame.open_screen("reports")
        frame.open_screen("users")
        self.assertIs(frame.content.winfo_children()[0], before)

    def test_change_password_dialog_flow(self):
        dialog = gui["dialogs"].ChangePasswordDialog(fake_tk.Widget(), self.cashier)
        dialog.old_var.set("secret1"); dialog.new_var.set("newpass1"); dialog.repeat_var.set("different")
        dialog._save()
        self.assertIn("не совпадают", dialog.error_var.get())
        dialog.repeat_var.set("newpass1")
        dialog._save()
        self.assertEqual(fake_tk.MESSAGEBOX.calls[-1][0], "info")
        auth.login("cash", "newpass1")                       # новый пароль действительно работает
        dialog.old_var.set("wrong"); dialog.new_var.set("another1"); dialog.repeat_var.set("another1")
        dialog._save()
        self.assertIn("Неверный текущий пароль", dialog.error_var.get())


class ScheduleFrameTests(SmokeBase):
    """Афиша: стена постеров на выбранный день; нажатие на постер открывает фильм."""

    def setUp(self):
        super().setUp()
        drama, comedy = genres.create_genre(self.admin, "Драма"), genres.create_genre(self.admin, "Комедия")
        self.poster = os.path.join(self._tmp.name, "poster.png")
        open(self.poster, "wb").close()
        self.dune = movies.create_movie(self.admin, "Дюна", drama, 155, "12+", "Описание фильма", self.poster)
        self.fun = movies.create_movie(self.admin, "Смешной фильм", comedy, 90, "6+")
        self.hall = halls.create_hall(self.admin, "Зал 1", 2, 5)
        mk = lambda movie, time, price: sessions.create_session(self.admin, movie, self.hall, "2026-10-17", time, price)
        self.s_dune_1, self.s_fun, self.s_dune_2 = mk(self.dune, "10:00", 350), mk(self.fun, "14:00", 300), mk(self.dune, "20:00", 450)

    def make(self, date="17.10.2026", user=None):
        frame = gui["schedule_frame"].ScheduleFrame(fake_tk.Widget(), user or self.viewer)
        frame.date_var.set(date)
        frame.load()
        return frame

    def test_tile_for_each_movie(self):
        frame = self.make()
        self.assertEqual([e["movie"]["id"] for e in frame._board], [self.dune, self.fun])   # по алфавиту
        self.assertIn("2", frame.status_var.get())
        self.assertEqual(len(frame._images), 2)        # у каждого фильма есть картинка (постер или заглушка)

    def test_tiles_never_overlap(self):
        """Плитки стоят в сетке с одинаковым шагом: постеры не могут «слипаться»."""
        schedule = gui["schedule_frame"]
        for width in (200, 400, 700, 1000, 1500):
            boxes = []
            for index in range(18):
                x, y, columns = schedule.tile_origin(index, width)
                boxes.append((x, y, x + schedule.TILE_W, y + schedule.TILE_H))
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    apart = a[2] + schedule.GAP <= b[0] or b[2] + schedule.GAP <= a[0] or \
                        a[3] + schedule.GAP <= b[1] or b[3] + schedule.GAP <= a[1]
                    self.assertTrue(apart, (width, a, b))
            self.assertLessEqual(max(b[2] for b in boxes[:columns]), max(width, schedule.TILE_W + 2 * schedule.GAP))

    def test_click_on_poster_opens_movie_for_the_chosen_date(self):
        frame = self.make()
        opened = []
        frame.on_open = lambda movie_id, date_iso: opened.append((movie_id, date_iso))
        frame._open(self.fun)
        self.assertEqual(opened, [(self.fun, "2026-10-17")])

    def test_click_flips_poster_to_description_and_back(self):
        frame = self.make()
        frame._draw()
        frame._clicked(self.dune)                          # первое нажатие переворачивает постер
        self.assertEqual(frame._flipped, {self.dune})
        for step in range(2 * gui["schedule_frame"].FLIP_STEPS + 2):
            frame._spin(self.dune, step, frame._generation)   # анимация доходит до конца без ошибок
        self.assertNotIn(self.dune, frame._busy)
        frame.canvas.canvasy = lambda value: value
        frame._clicked(self.dune, types.SimpleNamespace(y=0))   # нажатие мимо кнопки — переворот обратно
        self.assertEqual(frame._flipped, set())

    def test_go_button_on_back_side_opens_movie(self):
        frame = self.make()
        frame._draw()
        opened = []
        frame.on_open = lambda movie_id, date_iso: opened.append((movie_id, date_iso))
        frame.canvas.canvasy = lambda value: value
        frame.flip(self.fun)
        x, y, _ = frame._tiles[self.fun]
        button_y = y + gui["schedule_frame"].TILE_H - 30
        frame._clicked(self.fun, types.SimpleNamespace(y=button_y))
        self.assertEqual(opened, [(self.fun, "2026-10-17")])

    def test_reload_resets_flipped_posters(self):
        frame = self.make()
        frame._draw()
        frame.flip(self.dune)
        frame.load()
        self.assertEqual(frame._flipped, set())

    def test_started_sessions_are_not_advertised(self):
        with patch("services.clock.now", return_value=datetime(2026, 10, 17, 12, 0)), \
                patch("services.session_service._now", return_value=datetime(2026, 10, 17, 12, 0)):
            frame = self.make()
        times = {e["movie"]["id"]: gui["schedule_frame"].upcoming_times(e["sessions"]) for e in frame._board}
        self.assertEqual(times[self.dune], "20:00")                          # 10:00 уже прошёл
        self.assertEqual(times[self.fun], "14:00")

    def test_empty_day_and_invalid_date(self):
        frame = self.make("01.01.2030", user=self.admin)
        self.assertEqual(frame._board, [])
        self.assertIn("сеансов нет", frame.status_var.get())
        self.assertIn("«Сеансы»", frame.status_var.get())                      # подсказка только администратору
        self.assertNotIn("«Сеансы»", self.make("01.01.2030").status_var.get())
        frame.date_var.set("32.13.2026")
        frame.load()
        self.assertTrue(frame.error_var.get())

    def test_shift_today_and_wheel(self):
        frame = self.make()
        frame._shift(1)
        self.assertEqual((frame.date_var.get(), frame._board), ("18.10.2026", []))
        frame.date_var.set("2030-01-01")
        frame._today()
        self.assertEqual(frame.date_var.get(), "16.10.2026")                    # «сегодня» берётся из services.clock
        for event in (types.SimpleNamespace(delta=120, num=None), types.SimpleNamespace(delta=-1, num=None),
                      types.SimpleNamespace(delta=0, num=4), types.SimpleNamespace(delta=0, num=5)):
            frame._on_wheel(event)                                             # прокрутка колёсиком на всех ОС не падает
        frame._bind_wheel()
        frame._unbind_wheel()

    def test_all_roles_can_open_schedule(self):
        for user in (self.admin, self.cashier, self.viewer):
            self.assertEqual(len(self.make(user=user)._board), 2)


class AppTests(SmokeBase):
    def test_login_to_main_and_back(self):
        app = gui["app"].App(fake_tk.Widget(), admin_created=True)
        self.assertIsInstance(app._current, gui["login_frame"].LoginFrame)
        app.show_main(self.cashier)
        self.assertIsInstance(app._current, gui["main_frame"].MainFrame)
        app._current.on_logout()
        self.assertIsInstance(app._current, gui["login_frame"].LoginFrame)
        self.assertIsNone(app._first_run_notice)   # подсказка про admin/admin123 показывается один раз

    def test_unhandled_callback_exception_is_reported(self):
        app = gui["app"].App(fake_tk.Widget())
        with self.assertLogs("cinema", "ERROR"):
            app._on_callback_exception(RuntimeError, RuntimeError("x"), None)
        self.assertEqual(fake_tk.MESSAGEBOX.calls[-1][0], "error")
        with self.assertLogs("cinema", "ERROR"):
            app._on_callback_exception(ServiceError, ServiceError("Понятная ошибка"), None)
        self.assertEqual(fake_tk.MESSAGEBOX.calls[-1][:3:2], ("warning", "Понятная ошибка"))


if __name__ == "__main__":
    unittest.main()
