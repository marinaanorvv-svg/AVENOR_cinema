"""Приложение: окно, переключение «вход ↔ главное окно», перехват необработанных ошибок."""
import logging

from .common import apply_style, report_exception
from .login_frame import LoginFrame
from .main_frame import MainFrame

log = logging.getLogger("cinema")

BUILD = "3"   # номер сборки в заголовке окна: по нему видно, что запущена свежая версия


class App:
    def __init__(self, root, admin_created=False):
        self.root = root
        self._current = None
        self._first_run_notice = None      # подсказка «Первый запуск…» убрана по требованию
        root.title(f"AVENOR — информационная система кинотеатра (сборка {BUILD})")
        self._fit_window(root)
        apply_style(root)
        # Любая необработанная ошибка в обработчике кнопки не «молчит» в консоли,
        # а попадает в журнал и показывается пользователю.
        root.report_callback_exception = self._on_callback_exception
        self.show_login()

    @staticmethod
    def _fit_window(root):
        """Окно открывается крупным: почти весь экран (не меньше 1280x800, если экран позволяет), по центру."""
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(max(1280, int(screen_w * 0.92)), screen_w - 20, 1700)
        height = min(max(800, int(screen_h * 0.90)), screen_h - 80, 1050)
        x, y = max((screen_w - width) // 2, 0), max((screen_h - height) // 3, 0)
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.minsize(min(1100, width), min(680, height))

    def _replace(self, frame):
        if self._current is not None:
            self._current.destroy()
        self._current = frame
        frame.pack(fill="both", expand=True)

    def show_login(self):
        self._replace(LoginFrame(self.root, on_success=self.show_main, notice=self._first_run_notice))

    def show_main(self, user):
        self._first_run_notice = None
        self._replace(MainFrame(self.root, user, on_logout=self.show_login))

    def _on_callback_exception(self, exc_type, exc, traceback):
        log.error("Необработанная ошибка в обработчике", exc_info=(exc_type, exc, traceback))
        report_exception(self.root, exc)
