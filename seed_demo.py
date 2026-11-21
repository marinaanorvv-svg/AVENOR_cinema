"""Демо-данные для проверки программы:  python seed_demo.py

Создаёт жанры, 28 фильмов с постерами, залы, расписание на 7 дней, две учётные записи и несколько
проданных билетов — чтобы афиша, схема зала и отчёты не были пустыми.
Запускается один раз на пустой базе; все данные создаются через сервисы,
то есть с теми же проверками, что и в обычной работе программы.
"""
import random
import sys
from pathlib import Path
from datetime import timedelta

from database import crud
from database.connection import connection
from services import (auth_service, clock, genre_service, hall_service, movie_service,
                      session_service, ticket_service)
from services.errors import ServiceError
from services.permissions import Role

MOVIES = [  # (название, жанр, минут, возраст, описание, файл постера из папки demo_posters)
    ("Энола Холмс", "Детектив", 123, "12+", "Сестра знаменитого сыщика отправляется на поиски пропавшей матери и сама попадает в громкое дело.", "enola_holmes"),
    ("Бегущий в лабиринте", "Фантастика", 113, "12+", "Подростки живут в центре гигантского лабиринта и ищут из него выход.", "maze_runner"),
    ("Гадкий я 2", "Мультфильм", 98, "6+", "Бывший злодей Грю вместе с миньонами помогает агентам найти нового преступника.", "despicable_me_2"),
    ("Мстители: Война бесконечности", "Фантастика", 149, "12+", "Герои объединяются, чтобы остановить Таноса, который собирает камни бесконечности.", "avengers_infinity_war"),
    ("Гарри Поттер и философский камень", "Фэнтези", 152, "6+", "Мальчик узнаёт, что он волшебник, и отправляется учиться в Хогвартс.", "harry_potter"),
    ("Чарли и шоколадная фабрика", "Фэнтези", 115, "6+", "Мальчик находит золотой билет и попадает на загадочную фабрику Вилли Вонки.", "charlie_chocolate_factory"),
    ("Коралина в Стране кошмаров", "Мультфильм", 100, "12+", "Девочка находит дверь в другой мир, где всё кажется лучше, но за этим скрывается тайна.", "coraline"),
    ("Зверополис", "Мультфильм", 108, "6+", "Крольчиха-полицейская и хитрый лис вместе расследуют загадочные исчезновения.", "zootopia"),
    ("Титаник", "Мелодрама", 194, "12+", "История любви двух пассажиров на борту огромного лайнера в его первом рейсе.", "titanic"),
    ("Малефисента", "Фэнтези", 97, "12+", "Сказка о Спящей красавице, рассказанная с точки зрения злой феи.", "maleficent"),
    ("Проклятие Аннабель", "Ужасы", 99, "16+", "Молодая семья сталкивается со зловещей куклой, которая приносит в дом беду.", "annabelle"),
    ("Оно 2", "Ужасы", 169, "18+", "Спустя двадцать семь лет Клуб неудачников возвращается в город, чтобы победить Пеннивайза.", "it_chapter_two"),
    ("Алиса в Стране чудес", "Фэнтези", 108, "6+", "Алиса снова попадает в Страну чудес и должна помочь друзьям победить Червонную королеву.", "alice_wonderland"),
    ("Наследники", "Приключения", 112, "6+", "Дети знаменитых злодеев попадают в обычную школу и решают, кем им стать.", "descendants"),
    ("Один дома", "Комедия", 103, "6+", "Находчивый мальчик защищает дом от незадачливых грабителей.", "home_alone"),
    ("Наследники 3", "Приключения", 109, "6+", "Дети злодеев возвращаются в Орадон, чтобы остановить новую угрозу и спасти друзей.", "descendants_3"),
    ("Пять ночей с Фредди", "Ужасы", 109, "16+", "Ночной охранник заброшенной пиццерии узнаёт, что куклы-аниматроники оживают после закрытия.", "fnaf"),
    ("Как отделаться от парня за 10 дней", "Мелодрама", 116, "12+", "Журналистка пытается за десять дней отпугнуть парня, а он готов выдержать всё ради спора.", "how_to_lose_a_guy"),
    ("Мёртвая тишина", "Ужасы", 91, "16+", "Мужчина возвращается в родной город и сталкивается с проклятием старой куклы-чревовещателя.", "dead_silence"),
    ("Астрал", "Ужасы", 103, "16+", "Сын семьи впадает в загадочную кому, а в доме начинают происходить пугающие вещи.", "insidious"),
    ("Ночь в музее", "Комедия", 108, "6+", "Новый ночной сторож узнаёт, что экспонаты музея оживают, как только гаснет свет.", "night_at_museum"),
    ("Элвин и бурундуки", "Комедия", 92, "0+", "Три поющих бурундука поселяются у композитора и превращают его жизнь в весёлый хаос.", "alvin_chipmunks"),
    ("Каратэ-пацан", "Приключения", 140, "12+", "Мальчик переезжает в Китай и находит наставника в лице старого мастера кунг-фу.", "karate_kid"),
    ("Холодное сердце", "Мультфильм", 102, "6+", "Принцесса Анна отправляется в путь, чтобы найти сестру Эльзу и вернуть в королевство лето.", "frozen"),
    ("Монстр в Париже", "Мультфильм", 90, "6+", "В Париже 1910 года появляется огромный монстр, который оказывается добрым певцом.", "monster_in_paris"),
    ("Орудия смерти: Город костей", "Фэнтези", 130, "12+", "Девушка узнаёт, что принадлежит к древнему роду охотников на демонов, когда пропадает её мать.", "mortal_instruments"),
    ("Красная Шапочка", "Фэнтези", 100, "16+", "Деревня живёт в страхе перед оборотнем, а девушка подозревает, что чудовище — кто-то из близких.", "red_riding_hood"),
    ("Тепло наших тел", "Мелодрама", 97, "12+", "Зомби по имени Р влюбляется в живую девушку, и это меняет весь его мир.", "warm_bodies"),
]
HALLS = [  # (название, рядов, мест в ряду, VIP-ряды, цена билета)
    ("Зал 1", 8, 12, "7, 8", 350),
    ("Зал 2", 6, 10, "", 320),
    ("Малый зал", 5, 8, "", 300),
    ("Зал 3", 6, 10, "6", 330),
    ("VIP-зал", 3, 6, "1, 2, 3", 600),
]
TIMES = ("10:00", "12:30", "15:00", "17:30", "20:00", "22:30")   # удобные времена начала сеансов
FILMS_PER_DAY = [2, 1, 2, 1, 3, 1, 2, 1, 2, 2, 1, 2, 1, 2]   # сколько сеансов в день у очередного фильма: 1, 2 или 3
POSTERS_SRC = Path(__file__).resolve().parent / "demo_posters"
CLIENTS = [("Иван Петров", "+79990000001"), ("Мария Смирнова", "+79990000002"),
           ("Алексей Кузнецов", "+79990000003"), ("Ольга Попова", "+79990000004"),
           ("Дмитрий Соколов", "+79990000005")]
DAYS = 7


def database_is_empty() -> bool:
    with connection() as conn:
        return not (crud.list_movies(conn) or crud.list_halls(conn))


def populate(admin, seller=None) -> dict:
    """Заполняет пустую базу демо-данными от имени администратора. Возвращает числа для отчёта."""
    random.seed(42)   # одинаковые «случайные» билеты при каждом запуске
    genre_ids = {name: genre_service.create_genre(admin, name) for name in sorted({m[1] for m in MOVIES})}
    movie_ids = []
    for title, genre, minutes, age, text, poster in MOVIES:
        poster_file = POSTERS_SRC / f"{poster}.jpg"   # постера нет — в афише будет красивая заглушка
        movie_ids.append(movie_service.create_movie(admin, title, genre_ids[genre], minutes, age, text,
                                                    str(poster_file) if poster_file.is_file() else None))
    hall_ids, prices = {}, {}
    for name, rows, per_row, vip, price in HALLS:
        hall_ids[name] = hall_service.create_hall(admin, name, rows, per_row, vip)
        prices[name] = price

    today, created, skipped = clock.now().date(), 0, 0
    hall_names = list(hall_ids)
    for offset in range(DAYS):
        day = (today + timedelta(days=offset)).isoformat()
        for number, count in enumerate(FILMS_PER_DAY):
            movie_id = movie_ids[(offset * 5 + number) % len(movie_ids)]   # каждый день афиша немного сдвигается
            first_time = (number * 2) % len(TIMES)
            for j in range(count):                                          # у фильма 1–3 сеанса в разное время
                placed = False
                for shift in (0, 1, -1):                                    # не вышло — пробуем соседнее время
                    time_text = TIMES[(first_time + j * 2 + shift) % len(TIMES)]
                    for attempt in range(len(hall_names)):                  # свободный зал ищем по кругу
                        hall_name = hall_names[(number + j + attempt) % len(hall_names)]
                        try:
                            session_service.create_session(admin, movie_id, hall_ids[hall_name], day, time_text,
                                                           prices[hall_name])
                        except ServiceError:   # зал занят или время уже прошло — пробуем другой зал
                            continue
                        created, placed = created + 1, True
                        break
                    if placed:
                        break
                if not placed:
                    skipped += 1

    if seller is None:      # администратор билеты не продаёт: демо-продажи делает демо-кассир
        auth_service.ensure_demo_accounts()
        cashier_login = auth_service.DEMO_ACCOUNTS[Role.CASHIER]
        seller = auth_service.login(*cashier_login)
    sold = 0
    for session in session_service.list_sessions(admin, date_from=today, date_to=today + timedelta(days=1))[:10]:
        seats = [s["id"] for row in ticket_service.get_session_seat_map(seller, session["id"])["rows"]
                 for s in row["seats"]]
        name, phone = random.choice(CLIENTS)
        try:
            sold += len(ticket_service.sell_tickets(seller, session["id"], random.sample(seats, random.randint(2, 6)),
                                                    {"full_name": name, "phone": phone}))
        except ServiceError:
            pass
    return {"movies": len(movie_ids), "halls": len(hall_ids), "sessions": created, "skipped": skipped, "tickets": sold}


def populate_default() -> tuple[bool, str]:
    """Вход как admin / admin123 и заполнение пустой базы. Возвращает (успех, сообщение для пользователя)."""
    auth_service.ensure_default_admin()
    auth_service.ensure_demo_accounts()
    try:
        admin = auth_service.login(auth_service.DEFAULT_ADMIN_USERNAME, auth_service.DEFAULT_ADMIN_PASSWORD)
    except ServiceError:
        return False, "Не удалось войти как admin / admin123 (пароль уже изменён?). Демо-данные не добавлены."
    if not database_is_empty():
        return False, "В базе уже есть фильмы или залы — демо-данные не добавлены."
    stats = populate(admin)
    return True, (f"Готово: фильмов — {stats['movies']}, залов — {stats['halls']}, сеансов — {stats['sessions']} "
                  f"(пропущено прошедших: {stats['skipped']}), проданных билетов — {stats['tickets']}.")


def main() -> int:
    ok, message = populate_default()
    print(message)
    if ok:
        print("Учётные записи:")
        for role, (username, password) in auth_service.DEMO_ACCOUNTS.items():
            print(f"  {role:<8} {username} / {password}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
