"""Точка входа: python main.py"""
import logging
import sys
from pathlib import Path

# Демонстрационный режим для защиты проекта: у каждой роли есть готовая учётная запись, а при пустой базе
# программа предлагает загрузить тестовые данные. Для реальной работы поставьте False и смените пароли.
DEMO_MODE = True


def _setup_logging() -> None:
    """Ошибки и непредвиденные ситуации пишутся в cinema.log рядом с программой."""
    logging.basicConfig(
        filename=str(Path(__file__).resolve().parent / "cinema.log"),
        level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _offer_demo_data(root, messagebox) -> None:
    """Если в базе нет ни фильмов, ни залов — предлагает загрузить демонстрационные данные."""
    try:
        import seed_demo
        if not seed_demo.database_is_empty():
            return
        ok, message = seed_demo.populate_default()      # пустая база заполняется сама, без вопросов
        if not ok:
            logging.getLogger("cinema").warning("Демо-данные не загружены: %s", message)
            messagebox.showwarning("Демонстрационные данные", message, parent=root)
    except Exception:
        logging.getLogger("cinema").exception("Не удалось загрузить демонстрационные данные")
        messagebox.showerror("Ошибка", "Не удалось загрузить демонстрационные данные. Подробности — в cinema.log.",
                             parent=root)


def main() -> int:
    _setup_logging()
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError:
        print("Не найден модуль tkinter. На Linux установите пакет: sudo apt install python3-tk")
        return 1

    from gui.app import App
    from services import auth_service

    try:
        admin_created = auth_service.ensure_default_admin()   # создаёт БД и первого администратора
        if DEMO_MODE:
            auth_service.ensure_demo_accounts()               # демо-кассир и демо-пользователь
    except Exception:
        logging.getLogger("cinema").exception("Не удалось подготовить базу данных")
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Ошибка", "Не удалось открыть базу данных cinema.db.\n"
                                       "Проверьте права на папку программы. Подробности — в cinema.log.")
        return 1

    root = tk.Tk()
    App(root, admin_created)
    if DEMO_MODE:
        root.after(600, lambda: _offer_demo_data(root, messagebox))   # после показа окна входа
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
