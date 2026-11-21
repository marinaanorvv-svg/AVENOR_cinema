"""Фирменные виджеты и тема на заглушке tkinter. Запуск:  python -m unittest tests.test_gui_neon -v"""
import types
import unittest
import unittest.mock

from tests import fake_tk
from tests import test_gui_smoke as smoke


def setUpModule():
    smoke.setUpModule()


def tearDownModule():
    smoke.tearDownModule()


gui = smoke.gui


def click(widget, x=5, y=5):
    widget._released(types.SimpleNamespace(x=x, y=y)) if hasattr(widget, "_released") else None


class NeonWidgetTests(smoke.SmokeBase):
    def test_button_calls_command_only_on_click_inside_and_when_enabled(self):
        calls = []
        button = gui["neon"].NeonButton(fake_tk.Widget(), "Войти", lambda: calls.append(1))
        click(button)
        self.assertEqual(calls, [1])
        click(button, x=-10)                       # отпустили кнопку мыши вне кнопки — не нажатие
        self.assertEqual(calls, [1])
        button.set_enabled(False)
        click(button)
        self.assertEqual(calls, [1])
        button.set_enabled(True)
        click(button)
        self.assertEqual(calls, [1, 1])

    def test_button_hover_and_text_change(self):
        button = gui["neon"].NeonButton(fake_tk.Widget(), "Выйти", style="ghost", height=36, icon="logout")
        button._hover(True)
        self.assertTrue(button.hovered)
        button.set_text("Другой текст")
        self.assertEqual(button.label, "Другой текст")
        button.set_enabled(False)                   # у «ghost» нет отдельной картинки disabled — не должно падать
        button._hover(True)
        self.assertFalse(button.hovered)

    def test_passive_chip_has_no_click_handler(self):
        chip = gui["neon"].NeonButton(fake_tk.Widget(), "Анна · Кассир", style="ghost", height=36, icon="user", clickable=False)
        click(chip)                                 # ничего не происходит и не падает
        self.assertFalse(chip.clickable)

    def test_nav_item_active_state_and_click(self):
        calls = []
        item = gui["neon"].NavItem(fake_tk.Widget(), "Афиша", "home", lambda: calls.append("open"))
        item.set_active(True)
        self.assertTrue(item.active)
        item._hover(True)
        item.set_active(False)
        self.assertFalse(item.active)
        item.on_click()
        self.assertEqual(calls, ["open"])

    def test_entry_wraps_variable_and_forwards_focus(self):
        var = smoke.fake_tk.Var()
        field = gui["neon"].NeonEntry(fake_tk.Widget(), var, width=200, show="•")
        self.assertIsNotNone(field.entry)
        field.focus_set()
        field._draw("focus")
        field._draw("normal")

    def test_panel_redraws_and_exposes_body(self):
        panel = gui["neon"].RoundedPanel(fake_tk.Widget())
        panel._redraw()
        self.assertTrue(hasattr(panel, "body"))
        panel.winfo_width = lambda: 3                # слишком маленькая панель — просто пропускаем рисование
        panel._redraw()

    def test_stars_and_logo_draw_without_errors(self):
        canvas = fake_tk.Widget()
        gui["neon"].draw_stars(canvas, 400, 300, 20)
        gui["neon"].draw_logo(canvas, 10, 30)

    def test_poster_view_real_picture_placeholder_and_clear(self):
        import os
        real = os.path.join(self._tmp.name, "real.png")
        open(real, "wb").close()
        view = gui["neon"].PosterView(fake_tk.Widget(), "small")
        with unittest.mock.patch.object(gui["theme"], "_pillow_poster", return_value=None):
            view.show(real, "Название", 3)
            self.assertIsNotNone(view.shown)                      # настоящий PNG (без Pillow: через tk.PhotoImage)
            view.show(os.path.join(self._tmp.name, "нет.png"), "Название", 3)
        self.assertIs(view.shown, gui["theme"].load_image("poster_ph_3_small.png"))   # файла нет — заглушка
        view.show(None, "Название", 9)
        self.assertIs(view.shown, gui["theme"].load_image("poster_ph_3_small.png"))   # 9 % 6 == 3
        view.clear()
        self.assertIsNone(view.shown)

    def test_poster_loader_uses_pillow_result_first(self):
        import os
        real = os.path.join(self._tmp.name, "other.jpg")
        open(real, "wb").close()
        sentinel = object()
        with unittest.mock.patch.object(gui["theme"], "_pillow_poster", return_value=sentinel):
            self.assertIs(gui["theme"].load_poster(real, "large"), sentinel)
        with unittest.mock.patch.object(gui["theme"], "_pillow_poster", return_value=None):
            self.assertIsNone(gui["theme"].load_poster(os.path.join(self._tmp.name, "x.jpg"), "large"))   # JPG без Pillow — нет
        self.assertIsNone(gui["theme"].load_poster(None, "small"))

    def test_theme_loads_images_and_applies_fonts(self):
        theme = gui["theme"]
        self.assertIsNotNone(theme.load_image("logo_mark.png"))
        self.assertIs(theme.load_image("logo_mark.png"), theme.load_image("logo_mark.png"))   # кеш
        self.assertIsNone(theme.load_image("no_such_file.png"))                               # нет файла — не падаем
        theme.apply_theme(fake_tk.Widget())
        for key in ("body", "bold", "title", "hero", "logo", "nav", "nav_bold"):
            self.assertIn(key, theme.FONTS)

    def test_missing_assets_fall_back_to_plain_shapes(self):
        with unittest.mock.patch.object(gui["theme"], "load_image", return_value=None):
            canvas = fake_tk.Widget()
            size = gui["neon"].draw_pill(canvas, "primary", "normal", 44, 200)
            button = gui["neon"].NeonButton(fake_tk.Widget(), "Без картинок")
        self.assertEqual(size[1], 60)
        self.assertIsNotNone(button)

    def test_login_and_main_screens_build_with_new_theme(self):
        gui["theme"].apply_theme(fake_tk.Widget())
        login = gui["login_frame"].LoginFrame(fake_tk.Widget(), lambda user: None, notice="Первый запуск")
        self.assertTrue(login.username_entry.entry is not None)
        login._fill_demo("cashier")
        self.assertEqual((login.username_var.get(), login.password_var.get()), ("kassa", "kassa123"))
        main = gui["main_frame"].MainFrame(fake_tk.Widget(), self.cashier, on_logout=lambda: None)
        self.assertEqual([b.active for b in main.menu_buttons.values()], [True] + [False] * 5)   # первый пункт выбран
        main.open_screen("sale")
        self.assertEqual([b.active for b in main.menu_buttons.values()], [False, True] + [False] * 4)
        main._draw_deco(types.SimpleNamespace(width=256, height=600))
        main._draw_deco(types.SimpleNamespace(width=256, height=200))                              # низкое окно: без иллюстрации


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
