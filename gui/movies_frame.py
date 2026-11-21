"""Справочники «Фильмы» и «Жанры» (администратор)."""
import tkinter as tk
from tkinter import messagebox, ttk

from services import admin_service, genre_service, movie_service

from .common import ask_confirm, guarded
from .formatting import format_duration
from .forms import Field, FormDialog
from .sessions_frame import open_auto_schedule
from .widgets import Combo, DataTable, selected_int


class MoviesFrame(ttk.Frame):
    MOVIE_COLUMNS = (("title", "Название", 240), ("genre", "Жанр", 110),
                     ("duration", "Длительность", 100), ("age", "Возраст", 70))

    def __init__(self, parent, user):
        super().__init__(parent)
        self.user = user
        self.search_var = tk.StringVar()
        self._genres, self._movies = [], {}
        self._build_ui()
        self.reload_genres()
        self.reload_movies()

    # ------------------------------------------------------------------ интерфейс
    def _build_ui(self):
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(0, 14))
        ttk.Label(left, text="Жанры", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        self.genre_table = DataTable(left, (("name", "Жанр", 120), ("count", "Фильмов", 70)), height=14,
                                     on_select=self._on_genre_pick)
        self.genre_table.pack(fill="y", expand=True)
        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Добавить", command=self._add_genre).pack(side="left")
        ttk.Button(buttons, text="Переименовать", command=self._rename_genre).pack(side="left", padx=4)
        ttk.Button(buttons, text="Удалить", command=self._delete_genre).pack(side="left")
        ttk.Label(left, text="Нажмите на жанр — справа появятся его фильмы.", style="Muted.TLabel",
                  wraplength=230).pack(anchor="w", pady=(6, 0))

        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="Фильмы", style="Header.TLabel").pack(anchor="w", pady=(0, 6))
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Поиск:").pack(side="left")
        entry = ttk.Entry(bar, textvariable=self.search_var, width=24)
        entry.pack(side="left", padx=(4, 10))
        entry.bind("<KeyRelease>", lambda event: self.reload_movies())
        ttk.Label(bar, text="Жанр:").pack(side="left")
        self.genre_filter = Combo(bar, [(None, "Все жанры")], width=18, on_change=self.reload_movies)
        self.genre_filter.set_value(None)
        self.genre_filter.pack(side="left", padx=4)
        ttk.Button(bar, text="Сбросить", command=self._reset_filters).pack(side="left", padx=4)
        self.count_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.count_var, style="Muted.TLabel").pack(side="left", padx=8)
        self.movie_table = DataTable(right, self.MOVIE_COLUMNS, height=14, on_activate=self._edit_movie)
        self.movie_table.pack(fill="both", expand=True)
        buttons = ttk.Frame(right)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Добавить фильм", command=self._add_movie).pack(side="left")
        ttk.Button(buttons, text="Изменить", command=self._edit_movie).pack(side="left", padx=4)
        ttk.Button(buttons, text="Удалить", command=self._delete_movie).pack(side="left")

    # ------------------------------------------------------------------ данные
    def reload_genres(self):
        ok, genres = guarded(self, admin_service.list_genres_with_counts, self.user)
        if not ok:
            return
        self._genres = genres
        self.genre_table.set_rows((g["id"], (g["name"], g["movies"]), None) for g in genres)
        self.genre_filter.set_options([(None, "Все жанры")] + [(g["id"], g["name"]) for g in genres])

    def reload_movies(self):
        ok, movies = guarded(self, movie_service.list_movies, self.user,
                             genre_id=self.genre_filter.value(), search=self.search_var.get())
        if not ok:
            return
        self._movies = {m["id"]: m for m in movies}
        self.movie_table.set_rows(
            (m["id"], (m["title"], m["genre_name"], format_duration(m["duration"]), m["age_rating"]), None)
            for m in movies)
        self.count_var.set(f"Найдено: {len(movies)}")

    def _reset_filters(self):
        self.search_var.set("")
        self.genre_filter.set_value(None)
        self.reload_movies()

    def _on_genre_pick(self):
        """Выбор жанра слева показывает только его фильмы (список справа и фильтр «Жанр» синхронизируются)."""
        iid = self.genre_table.selected_id()
        if iid is not None and self.genre_filter.value() != int(iid):
            self.genre_filter.set_value(int(iid))
            self.reload_movies()

    def _after_genre_change(self):
        self.reload_genres()
        self.reload_movies()

    # ------------------------------------------------------------------ жанры
    def _genre_by_id(self, genre_id):
        return next(g for g in self._genres if g["id"] == genre_id)

    def _add_genre(self):
        FormDialog(self, "Новый жанр", [Field("name", "Название")],
                   on_submit=lambda v: genre_service.create_genre(self.user, v["name"]),
                   on_saved=self._after_genre_change)

    def _rename_genre(self):
        genre_id = selected_int(self, self.genre_table, "Выберите жанр в таблице.")
        if genre_id is None:
            return
        genre = self._genre_by_id(genre_id)
        FormDialog(self, "Переименовать жанр", [Field("name", "Название", value=genre["name"])],
                   on_submit=lambda v: genre_service.rename_genre(self.user, genre_id, v["name"]),
                   on_saved=self._after_genre_change)

    def _delete_genre(self):
        genre_id = selected_int(self, self.genre_table, "Выберите жанр в таблице.")
        if genre_id is None:
            return
        genre = self._genre_by_id(genre_id)
        if ask_confirm(self, f"Удалить жанр «{genre['name']}»?"):
            ok, _ = guarded(self, genre_service.delete_genre, self.user, genre_id)
            if ok:
                self._after_genre_change()

    # ------------------------------------------------------------------ фильмы
    def _movie_fields(self, movie=None):
        value = lambda key, default="": movie[key] if movie and movie[key] is not None else default
        return [
            Field("title", "Название", value=value("title")),
            Field("genre_id", "Жанр", "combo", options=tuple((g["id"], g["name"]) for g in self._genres),
                  value=value("genre_id", None)),
            Field("duration", "Длительность, мин", value=value("duration"), hint="От 1 до 600 минут"),
            Field("age_rating", "Возраст", "combo",
                  options=tuple((r, r) for r in movie_service.AGE_RATINGS), value=value("age_rating", "0+")),
            Field("description", "Описание", "text", value=value("description")),
            Field("poster_path", "Постер", "file", value=value("poster_path"),
                  hint="В афише показываются PNG и GIF",
                  filetypes=(("Изображения", "*.png *.gif *.jpg *.jpeg"),)),
        ]

    def _add_movie(self):
        if not self._genres:
            messagebox.showinfo("Нет жанров", "Сначала добавьте хотя бы один жанр.", parent=self)
            return
        created = []

        def submit(v):
            created.append(movie_service.create_movie(
                self.user, v["title"], v["genre_id"], v["duration"], v["age_rating"], v["description"], v["poster_path"]))

        def saved():
            self.reload_movies()
            if created and messagebox.askyesno("Фильм добавлен", "Сразу назначить сеансы на ближайшую неделю?",
                                               parent=self):
                ok, movies = guarded(self, movie_service.list_movies, self.user)
                if ok:
                    open_auto_schedule(self, self.user, movies, movie_id=created[0])

        FormDialog(self, "Новый фильм", self._movie_fields(), on_submit=submit, on_saved=saved,
                   submit_text="Добавить фильм")

    def _edit_movie(self):
        movie_id = selected_int(self, self.movie_table, "Выберите фильм в таблице.")
        if movie_id is None:
            return
        ok, movie = guarded(self, movie_service.get_movie, self.user, movie_id)   # свежие данные из БД
        if not ok:
            return
        FormDialog(
            self, "Изменить фильм", self._movie_fields(movie),
            on_submit=lambda v: movie_service.update_movie(self.user, movie_id, **v),
            on_saved=self.reload_movies)

    def _delete_movie(self):
        movie_id = selected_int(self, self.movie_table, "Выберите фильм в таблице.")
        if movie_id is None:
            return
        if ask_confirm(self, f"Удалить фильм «{self._movies[movie_id]['title']}»?"):
            ok, _ = guarded(self, movie_service.delete_movie, self.user, movie_id)
            if ok:
                self.reload_movies()
