"""Экран входа: слева афиша-иллюстрация и слоган, справа светящаяся карточка с формой."""
import tkinter as tk

from services import auth_service
from services.errors import AuthenticationError, ServiceError

from . import neon
from . import palette as P
from . import theme
from .common import report_exception
from .login_guard import LoginAttemptLimiter


class LoginFrame(tk.Frame):
    def __init__(self, parent, on_success, notice=None):
        """on_success(user) вызывается после успешного входа; notice — подсказка над формой."""
        super().__init__(parent, bg=P.BG)
        self.on_success = on_success
        self.limiter = LoginAttemptLimiter()
        self.username_var, self.password_var = tk.StringVar(), tk.StringVar()
        self.message_var = tk.StringVar()
        self._notice = notice
        self._build_ui()

    def _label(self, parent, text, font_key="body", color=P.TEXT, bg=P.BG, **options):
        return tk.Label(parent, text=text, font=theme.font(font_key), fg=color, bg=bg, **options)

    def _build_ui(self):
        # звёздное небо на заднем плане (остальное кладётся поверх)
        self.sky = tk.Canvas(self, bg=P.BG, bd=0, highlightthickness=0)
        self.sky.place(x=0, y=0, relwidth=1, relheight=1)
        self.sky.bind("<Configure>", lambda event: neon.draw_stars(self.sky, event.width, event.height, 140))

        left = tk.Frame(self, bg=P.BG)
        left.place(relx=0.045, rely=0.5, anchor="w")
        logo = tk.Canvas(left, width=260, height=60, bg=P.BG, bd=0, highlightthickness=0)
        logo.pack(anchor="w", pady=(0, 14))
        neon.draw_logo(logo, 0, 30)
        hero = theme.load_image("login_hero.png")
        if hero:
            tk.Label(left, image=hero, bg=P.BG, bd=0).pack(anchor="w", pady=(0, 18))
        self._label(left, "Билеты на лучшие сеансы — в пару кликов", "hero", wraplength=540, justify="left").pack(anchor="w")
        self._label(left, "Афиша, продажа и отчёты в одном окне.", "body", P.MUTED).pack(anchor="w", pady=(8, 0))

        panel = neon.RoundedPanel(self, fill=P.PANEL, bg=P.BG, pad=22)
        panel.place(relx=0.79, rely=0.5, anchor="center", width=420, height=540)
        body = panel.body
        self._label(body, "Вход в систему", "h2", bg=P.PANEL).pack(anchor="w", pady=(2, 10))
        if self._notice:
            self._label(body, self._notice, "small", P.ACCENT_SOFT, P.PANEL, wraplength=350, justify="left").pack(anchor="w", pady=(0, 8))
        self._label(body, "Быстрый вход (демо-доступ):", "small", P.MUTED, P.PANEL).pack(anchor="w")
        roles = tk.Frame(body, bg=P.PANEL)
        roles.pack(anchor="w", pady=(2, 10))
        for role, title in (("admin", "Админ"), ("cashier", "Кассир"), ("viewer", "Покупатель")):
            neon.NeonButton(roles, title, lambda r=role: self._fill_demo(r), style="ghost", height=36, width=92,
                            bg=P.PANEL).pack(side="left", padx=(0, 4))
        self._label(body, "Логин", "small", P.MUTED, P.PANEL).pack(anchor="w")
        self.username_entry = neon.NeonEntry(body, self.username_var, width=338, bg=P.PANEL)
        self.username_entry.pack(anchor="w", pady=(2, 8))
        self._label(body, "Пароль", "small", P.MUTED, P.PANEL).pack(anchor="w")
        self.password_entry = neon.NeonEntry(body, self.password_var, width=338, show="•", bg=P.PANEL)
        self.password_entry.pack(anchor="w", pady=(2, 4))
        self._label(body, "", "small", P.ERROR, P.PANEL, textvariable=self.message_var, wraplength=350,
                    justify="left", height=2, anchor="nw").pack(anchor="w", fill="x")
        neon.NeonButton(body, "Войти", self._on_login, style="primary", width=338, bg=P.PANEL).pack(anchor="w", pady=(2, 0))

        self.username_entry.entry.bind("<Return>", lambda event: self.password_entry.focus_set())
        self.password_entry.entry.bind("<Return>", lambda event: self._on_login())
        self.after(150, self.username_entry.focus_set)

    def _fill_demo(self, role):
        """Подставляет логин и пароль демо-учётки выбранной роли (см. auth_service.DEMO_ACCOUNTS)."""
        username, password = auth_service.DEMO_ACCOUNTS[role]
        self.username_var.set(username)
        self.password_var.set(password)
        self.message_var.set("")
        self.password_entry.focus_set()

    def _on_login(self):
        wait = self.limiter.seconds_left()
        if wait:
            self.message_var.set(f"Слишком много неудачных попыток. Повторите через {wait} с.")
            return
        try:
            user = auth_service.login(self.username_var.get(), self.password_var.get())
        except AuthenticationError as exc:
            locked = self.limiter.register_failure()
            text = str(exc)
            if locked:
                text += f" Вход заблокирован на {self.limiter.lock_seconds} с."
            self.message_var.set(text)
            self.password_var.set("")
            self.password_entry.focus_set()
            return
        except ServiceError as exc:   # например, пустые поля
            self.message_var.set(str(exc))
            return
        except Exception as exc:      # баг или недоступная БД
            report_exception(self, exc)
            return
        self.limiter.register_success()
        self.message_var.set("")
        self.password_var.set("")     # пароль не должен оставаться в памяти формы
        self.on_success(user)
