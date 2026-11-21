"""Общие помощники для окон: оформление и показ ошибок."""
import logging
from tkinter import messagebox

from services.errors import ServiceError

from . import palette as P
from . import theme

log = logging.getLogger("cinema")

ERROR_COLOR = P.ERROR
MUTED_COLOR = P.MUTED


def apply_style(root) -> None:
    """Единое оформление приложения (тема «неон», см. gui/theme.py)."""
    theme.apply_theme(root)


def center_on_parent(window, parent, width=None, height=None) -> None:
    """Размещает диалог по центру родительского окна (размер по содержимому, если не задан)."""
    window.update_idletasks()
    width = width or window.winfo_reqwidth()
    height = height or window.winfo_reqheight()
    top = parent.winfo_toplevel()
    x = top.winfo_rootx() + max((top.winfo_width() - width) // 2, 0)
    y = top.winfo_rooty() + max((top.winfo_height() - height) // 3, 0)
    window.geometry(f"{width}x{height}+{x}+{y}")


def unexpected_error_text(exc: BaseException) -> str:
    """Текст окна «Непредвиденная ошибка»: вид ошибки и её сообщение видны сразу (по снимку экрана понятно,
    что сломалось), полная трассировка — в cinema.log."""
    detail = f"{type(exc).__name__}: {exc}".strip()
    if len(detail) > 300:
        detail = detail[:300].rstrip() + "…"
    return ("Произошла непредвиденная ошибка.\n\n" + detail +
            "\n\nПодробности записаны в файл cinema.log (рядом с main.py).")


def report_exception(parent, exc: BaseException) -> None:
    """Показывает ошибку пользователю.

    ServiceError (неверный ввод, нет прав, место занято...) — понятное предупреждение.
    Любая другая — это баг: пишем подробности в cinema.log, пользователю — короткое сообщение.
    """
    if isinstance(exc, ServiceError):
        messagebox.showwarning("Внимание", str(exc), parent=parent)
        return
    log.error("Непредвиденная ошибка", exc_info=exc)
    messagebox.showerror("Ошибка", unexpected_error_text(exc), parent=parent)


def guarded(parent, func, *args, **kwargs):
    """Вызывает func(*args); любую ошибку показывает пользователю и не роняет окно.

    Возвращает (успех, результат): `ok, tickets = guarded(self, sell_tickets, ...)`.
    """
    try:
        return True, func(*args, **kwargs)
    except Exception as exc:   # ServiceError -> предупреждение, остальное -> журнал + сообщение
        report_exception(parent, exc)
        return False, None


def ask_confirm(parent, message: str) -> bool:
    return messagebox.askyesno("Подтверждение", message, parent=parent)
