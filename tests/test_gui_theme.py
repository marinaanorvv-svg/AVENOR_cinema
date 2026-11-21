"""Тема и картинки без tkinter: палитра, геометрия «таблеток», наличие и размеры PNG, иконки меню."""
import os
import struct
import unittest

from gui import assets_spec as spec
from gui import palette as P
from gui.navigation import MENU_ITEMS

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui", "assets")


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path}: это не PNG"
    return struct.unpack(">II", head[16:24])


class PaletteTests(unittest.TestCase):
    def test_blend(self):
        self.assertEqual(P.blend("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(P.blend("#000000", "#ffffff", 1), "#ffffff")
        self.assertEqual(P.blend("#000000", "#ffffff", 0.5), "#808080")

    def test_pick_font_family(self):
        self.assertEqual(P.pick_font_family(["Arial", "segoe ui"]), "segoe ui")        # без учёта регистра, по приоритету
        self.assertEqual(P.pick_font_family(["Comic Sans"]), "Helvetica")             # ничего подходящего — запасной

    def test_rounded_points_stay_inside_and_clamp_radius(self):
        pts = P.rounded_points(10, 20, 110, 70, 15)
        xs, ys = pts[0::2], pts[1::2]
        self.assertTrue(10 <= min(xs) and max(xs) <= 110 and 20 <= min(ys) and max(ys) <= 70)
        tiny = P.rounded_points(0, 0, 10, 10, 99)               # радиус больше половины стороны не ломает фигуру
        self.assertTrue(all(0 <= v <= 10 for v in tiny))

    def test_stars_are_deterministic_and_in_bounds(self):
        first, second = P.star_points(300, 200, 50), P.star_points(300, 200, 50)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 50)
        self.assertTrue(all(0 <= x < 300 and 0 <= y < 200 for x, y, _, _ in first))


class AssetTests(unittest.TestCase):
    def test_pill_geometry(self):
        self.assertEqual(spec.pill_geometry(214, 44), (11, 236, 60))     # меню: 11 средних кусков
        self.assertEqual(spec.pill_geometry(338, 44), (19, 364, 60))     # поле и кнопка входа
        tiles, width, height = spec.pill_geometry(10, 44)                # слишком узкая — только края
        self.assertEqual((tiles, width, height), (0, 60, 60))
        for inner in range(40, 400, 7):                                  # ширина всегда не меньше запрошенной
            _, total, _ = spec.pill_geometry(inner, 36)
            self.assertGreaterEqual(total - 2 * spec.MARGIN, inner)
            self.assertLess(total - 2 * spec.MARGIN - inner, spec.TILE)

    def test_all_required_files_exist(self):
        missing = [n for n in spec.required_assets() if not os.path.isfile(os.path.join(ASSETS, n))]
        self.assertEqual(missing, [], "запустите: python tools/make_assets.py")

    def test_pill_pieces_have_consistent_sizes(self):
        for style, states in spec.PILL_STATES.items():
            for state in states:
                for height in spec.HEIGHTS:
                    cap = spec.MARGIN + height // 2
                    sizes = {part: png_size(os.path.join(ASSETS, spec.pill_asset_name(style, state, height, part)))
                             for part in spec.PARTS}
                    self.assertEqual(sizes["left"], (cap, height + 2 * spec.MARGIN), (style, state, height))
                    self.assertEqual(sizes["right"], sizes["left"])
                    self.assertEqual(sizes["tile"], (spec.TILE, height + 2 * spec.MARGIN))

    def test_icons_have_expected_size(self):
        for name in spec.ICON_NAMES:
            for color in spec.ICON_COLORS:
                self.assertEqual(png_size(os.path.join(ASSETS, spec.icon_asset_name(name, color))), (spec.ICON_SIZE,) * 2)

    def test_poster_placeholders_have_card_sizes_and_wrap_around(self):
        for index in range(spec.POSTER_PLACEHOLDERS):
            for size, expected in spec.POSTER_SIZES.items():
                self.assertEqual(png_size(os.path.join(ASSETS, spec.poster_placeholder_name(index, size))), expected)
        self.assertEqual(spec.poster_placeholder_name(spec.POSTER_PLACEHOLDERS + 2, "small"), spec.poster_placeholder_name(2, "small"))

    def test_every_menu_item_has_a_real_icon(self):
        for item in MENU_ITEMS:
            self.assertIn(item.icon, spec.ICON_NAMES, item.key)


if __name__ == "__main__":
    unittest.main()
