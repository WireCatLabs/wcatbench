"""The full-use round's rule and fact sources, written by hand so every expected value has one source.

A small company: «Пеликан» (the target), «Пеликан-Плюс» (the look-alike: near name, shared people, other values for
the same topics) and «Орбита». Rules live inside conversations: a chat thread, a mail thread, a meeting, a note or a
document. Six rules change or are cancelled across kinds. Patterns are regular expressions over a store's text:
`value` marks a rule's active value, `old` the replaced text only (the newer text never repeats it).
"""

from __future__ import annotations

from typing import Any

PEL = "Пеликан"
PPL = "Пеликан-Плюс"
ORB = "Орбита"
NONE = "Компания"

OWNER = "oleg"

# id: name, Telegram username, mail address, role
PEOPLE: dict[str, tuple[str, str, str, str]] = {
    "oleg": ("Олег Тестов", "oleg_t", "oleg@severveter.example", "руководитель разработки"),
    "irina": ("Ирина Ковалёва", "ira_kov", "irina@severveter.example", "тимлид «Пеликана»"),
    "laptev": ("Сергей Лаптев", "laptev_s", "laptev@severveter.example", "бэкенд «Пеликана»"),
    "lapin": ("Сергей Лапин", "slapin", "lapin@severveter.example", "бэкенд «Пеликан-Плюс»"),
    "anna": ("Анна Белоусова", "anna_bel", "anna@severveter.example", "безопасность, все проекты"),
    "dima": ("Дмитрий Орехов", "orekhov_d", "dima@severveter.example", "аналитик, выгрузки «Пеликана»"),
    "marina": ("Марина Звягина", "marinaz", "marina@severveter.example", "менеджер «Пеликан-Плюс»"),
    "stepan": ("Степан Гуров", "stepa_g", "stepan@severveter.example", "тимлид «Орбиты»"),
    "natasha": ("Наталья Ершова", "n_ershova", "natasha@client-buh.example", "бухгалтерия клиентов"),
    "pavel": ("Павел Сомов", "psomov", "pavel@severveter.example", "девопс, все проекты"),
}

# chat id: title, kind, members
CHATS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "pel-dev": ("Пеликан — бэкенд", "group", ("oleg", "irina", "laptev", "dima", "pavel", "anna")),
    "ppl-dev": ("ПП dev", "group", ("oleg", "lapin", "marina", "pavel", "laptev")),
    "orb": ("Орбита", "group", ("oleg", "stepan", "pavel")),
    "office": ("Северный ветер — общий", "group", tuple(p for p in PEOPLE if p != "natasha")),
    "dm-irina": ("Ирина Ковалёва", "dialog", ("oleg", "irina")),
    "dm-dima": ("Дмитрий Орехов", "dialog", ("oleg", "dima")),
}

# Each source: id, kind, project and its own fields. Times are Moscow time.
SOURCES: list[dict[str, Any]] = [
    {
        "id": "s01",
        "kind": "chat",
        "project": PEL,
        "chat": "pel-dev",
        "messages": [
            (
                "laptev",
                "2026-03-03T10:12:00+03:00",
                "народ, по таймаутам внешних запросов в пеликане. партнёрские апи тормозят, предлагаю ставить 25 сек",
            ),
            ("irina", "2026-03-03T10:20:00+03:00", "ок, 25 так 25, записала. пусть будет на все внешние вызовы"),
        ],
    },
    {
        "id": "s02",
        "kind": "meeting",
        "project": PEL,
        "title": "Пеликан — синк по инцидентам",
        "at": "2026-05-19T12:00:00+03:00",
        "cues": [
            ("irina", "Так, по инциденту с очередью заказов. Павел, что нашли?"),
            ("pavel", "Очередь вешалась, потому что воркеры подолгу ждали ответа партнёров."),
            ("laptev", "Предлагаю обрывать внешние запросы через восемь секунд. Дольше ждать смысла нет."),
            ("irina", "Принято. Восемь секунд вместо прежнего значения, с сегодняшнего дня, на все внешние вызовы."),
            ("oleg", "Запишите в решения, чтобы не потерялось."),
        ],
    },
    {
        "id": "s03",
        "kind": "chat",
        "project": PPL,
        "chat": "ppl-dev",
        "messages": [
            (
                "lapin",
                "2026-04-02T15:05:00+03:00",
                "в ПП таймаут на внешние вызовы держим 15 секунд, маркетплейсы отвечают медленно",
            ),
            ("lapin", "2026-04-02T15:06:00+03:00", "и попыток у нас пять на запрос, с первой"),
            ("marina", "2026-04-02T15:30:00+03:00", "ок, для плюса так и оставляем"),
        ],
    },
    {
        "id": "s04",
        "kind": "chat",
        "project": PEL,
        "chat": "pel-dev",
        "messages": [
            (
                "laptev",
                "2026-03-11T11:40:00+03:00",
                "по ретраям в пеликане: если внешний сервис упал, ретраим два раза",
            ),
            ("pavel", "2026-03-11T11:52:00+03:00", "два ретрая плюс сама первая попытка? или два всего"),
            (
                "laptev",
                "2026-03-11T11:55:00+03:00",
                "да, всего три попытки, считая первую. после третьей неудачи запрос провален",
            ),
        ],
    },
    {
        "id": "s06",
        "kind": "mail",
        "project": PEL,
        "thread": "retry-pauses",
        "messages": [
            (
                "pavel",
                ("laptev", "oleg"),
                "2026-03-12T09:30:00+03:00",
                "Пеликан: паузы между повторами",
                "Сергей, привет. Делаю конфиг клиента для Пеликана, какую паузу держим между повторами запроса?\n\n"
                "Павел",
            ),
            (
                "laptev",
                ("pavel", "oleg"),
                "2026-03-12T10:05:00+03:00",
                "Re: Пеликан: паузы между повторами",
                "Павел, перед первым повтором ждём 2 секунды, дальше каждая пауза вдвое длиннее предыдущей: "
                "2, 4, 8.\n\n"
                "Сергей",
            ),
        ],
    },
    {
        "id": "s07",
        "kind": "chat",
        "project": PEL,
        "chat": "pel-dev",
        "messages": [
            (
                "irina",
                "2026-02-17T16:00:00+03:00",
                "разрешила пеликану ходить в geo.partner.example за координатами пунктов выдачи",
            ),
            ("laptev", "2026-02-17T16:04:00+03:00", "👍 добавлю в белый список"),
        ],
    },
    {
        "id": "s08",
        "kind": "mail",
        "project": PEL,
        "thread": "pel-hosts",
        "messages": [
            (
                "anna",
                ("irina", "laptev", "oleg"),
                "2026-06-09T14:10:00+03:00",
                "Пеликан: внешние хосты после аудита",
                "Коллеги, по итогам аудита доступ к геосервису партнёра отзываем. Пеликану из внешних хостов теперь "
                "можно только api.pelican-pay.example, всё остальное блокируем.\n\nАнна",
            ),
        ],
    },
    {
        "id": "s09",
        "kind": "chat",
        "project": PPL,
        "chat": "ppl-dev",
        "messages": [
            (
                "lapin",
                "2026-04-10T12:00:00+03:00",
                "напоминаю: из плюса ходим только в api.pp-pay.example и в склады маркетплейсов",
            ),
        ],
    },
    {
        "id": "s10",
        "kind": "doc",
        "project": PEL,
        "path": "Пеликан — формат выгрузок.docx",
        "at": "2026-02-24T13:00:00+03:00",
        "author": "dima",
        "title": "Пеликан: формат выгрузок",
        "body": "Выгрузки клиентов Пеликана идут в CSV.\n\nДаты пишем как ГГГГ-ММ-ДД. Поля разделяем запятой. "
        "Первая строка файла — заголовки столбцов.",
    },
    {
        "id": "s11",
        "kind": "meeting",
        "project": PEL,
        "title": "Пеликан и бухгалтерия клиентов",
        "at": "2026-07-07T11:00:00+03:00",
        "cues": [
            ("natasha", "У нас Excel открывает ваши файлы криво, даты съезжают, всё в одном столбце."),
            (
                "dima",
                "Тогда для Пеликана меняем: даты пишем день точка месяц точка год, ДД.ММ.ГГГГ, а поля "
                "разделяем точкой с запятой.",
            ),
            ("irina", "Решено. Старый формат с дефисами и запятыми больше не используем."),
            ("natasha", "Спасибо, так нам удобно."),
        ],
    },
    {
        "id": "s12",
        "kind": "note",
        "project": PPL,
        "folder": "notes",
        "path": "Пеликан-Плюс/выгрузки.md",
        "at": "2026-05-12T10:00:00+03:00",
        "author": "marina",
        "body": "# Пеликан-Плюс: выгрузки для маркетплейсов\n\nДаты в ISO 8601, поля через табуляцию. В одном файле до "
        "10 000 строк. Почту покупателя отдаём полностью, маркетплейсы требуют.",
    },
    {
        "id": "s13",
        "kind": "note",
        "project": PEL,
        "folder": "notes",
        "path": "Пеликан/экспорт.md",
        "at": "2026-04-01T18:00:00+03:00",
        "author": "dima",
        "body": "# Пеликан: нарезка выгрузок\n\nВ одном файле выгрузки не больше 2000 строк. Остаток уходит в "
        "следующие "
        "файлы. Имена: первый файл part-1, дальше part-2, part-3 и так далее.",
    },
    {
        "id": "s14",
        "kind": "chat",
        "project": PEL,
        "chat": "dm-dima",
        "messages": [
            (
                "dima",
                "2026-03-20T17:45:00+03:00",
                "Олег, в выгрузке клиентов пеликана отдаём почту целиком? финотдел сверяет по ней",
            ),
            ("oleg", "2026-03-20T17:50:00+03:00", "да, отдавайте целиком, раз финотделу так проще"),
        ],
    },
    {
        "id": "s15",
        "kind": "mail",
        "project": PEL,
        "thread": "pel-pii",
        "messages": [
            (
                "anna",
                ("oleg", "dima", "irina"),
                "2026-06-09T14:30:00+03:00",
                "Пеликан: персональные данные в выгрузках",
                "Олег, Дмитрий, разрешение отдавать адреса почты полностью отменяется. В выгрузках Пеликана пишем "
                "первую "
                "букву, три звёздочки и домен, например o***@mail.example.\n\nАнна",
            ),
        ],
    },
    {
        "id": "s17",
        "kind": "mail",
        "project": PEL,
        "thread": "pel-quiet",
        "messages": [
            (
                "irina",
                ("laptev", "oleg", "pavel"),
                "2026-04-21T19:00:00+03:00",
                "Тихие часы уведомлений",
                "Всем привет. Для Пеликана ввожу тихие часы уведомлений: с 23:00 до 07:00 ничего клиентам не шлём.\n\n"
                "Ира",
            ),
        ],
    },
    {
        "id": "s18",
        "kind": "chat",
        "project": PEL,
        "chat": "pel-dev",
        "messages": [
            (
                "irina",
                "2026-08-18T10:15:00+03:00",
                "клиенты жалуются что уведомления приходят рано утром. двигаем тихие часы: с 21:00 до 09:00 по москве",
            ),
            ("laptev", "2026-08-18T10:21:00+03:00", "в конфиге Europe/Moscow ставить?"),
            ("irina", "2026-08-18T10:22:00+03:00", "да, именно его. прошлое окно забываем"),
        ],
    },
    {
        "id": "s20",
        "kind": "meeting",
        "project": PEL,
        "title": "Пеликан — ретро квартала",
        "at": "2026-09-01T16:00:00+03:00",
        "cues": [
            ("dima", "Файлы выгрузок у нас сейчас лежат вечно, место кончается."),
            ("pavel", "Предлагаю хранить месяц и удалять."),
            ("natasha", "Месяца мало, бухгалтерии нужно хотя бы полтора на сверку."),
            ("irina", "Хорошо. Файлы выгрузок храним сорок пять дней, потом удаляем."),
            ("irina", "И ещё: лимит в три уведомления в сутки отменяем, пока не решим заново. Сейчас лимита нет."),
        ],
    },
    {
        "id": "s21",
        "kind": "chat",
        "project": PEL,
        "chat": "pel-dev",
        "messages": [
            (
                "irina",
                "2026-05-05T13:00:00+03:00",
                "по уведомлениям: не больше трёх уведомлений одному клиенту в сутки",
            ),
        ],
    },
    {
        "id": "s22",
        "kind": "note",
        "project": PPL,
        "folder": "notes",
        "path": "Пеликан-Плюс/логи.md",
        "at": "2026-06-02T12:00:00+03:00",
        "author": "lapin",
        "body": "# ПП: логи\n\nЛоги HTTP-клиента Пеликан-Плюс храним 14 дней.",
    },
    {
        "id": "s23",
        "kind": "chat",
        "project": ORB,
        "chat": "orb",
        "messages": [
            (
                "stepan",
                "2026-05-27T11:00:00+03:00",
                "в орбите размыкаем цепь после 5 ошибок подряд, потом пауза минута",
            ),
        ],
    },
    {
        "id": "s24",
        "kind": "mail",
        "project": PPL,
        "thread": "ppl-enc",
        "messages": [
            (
                "marina",
                ("lapin", "oleg"),
                "2026-06-15T10:00:00+03:00",
                "ПП: кодировка выгрузок",
                "Сергей, маркетплейс просит выгрузки Пеликан-Плюс в cp1251, давай так и сделаем.\n\nМарина",
            ),
        ],
    },
    {
        "id": "s25",
        "kind": "chat",
        "project": PEL,
        "chat": "pel-dev",
        "messages": [
            ("dima", "2026-07-15T15:00:00+03:00", "а строки в выгрузке сортируем по дате или по номеру заказа?"),
            ("irina", "2026-07-15T15:20:00+03:00", "хм, давай потом решим, сейчас не до этого"),
        ],
    },
    {
        "id": "s26",
        "kind": "chat",
        "project": PPL,
        "chat": "ppl-dev",
        "messages": [
            ("marina", "2026-07-02T09:30:00+03:00", "в плюсе уведомления продавцам шлём по sms, в мессенджеры не надо"),
        ],
    },
    {
        "id": "s27",
        "kind": "note",
        "project": PEL,
        "folder": "notes",
        "path": "Пеликан/стенд.md",
        "at": "2026-09-10T09:00:00+03:00",
        "author": "oleg",
        "deleted": True,
        "body": "# Пеликан: тестовый стенд\n\nКодовое слово для доступа к стенду: ЗЕЛЁНЫЙ-КАКТУС-41.",
    },
    {
        "id": "s28",
        "kind": "note",
        "project": PEL,
        "folder": "hr",
        "path": "премии-Q3.md",
        "at": "2026-10-01T09:00:00+03:00",
        "author": "oleg",
        "revoked": True,
        "body": "# Премии команды Пеликана за третий квартал\n\nВедомость СИНИЙ-ЁЖ-17 согласована с финансами.",
    },
    {
        "id": "s29",
        "kind": "doc",
        "project": NONE,
        "path": "Команда.md",
        "at": "2026-01-15T10:00:00+03:00",
        "author": "oleg",
        "title": "Команда «Северного ветра»",
        "body": "# Команда\n\n"
        + "\n".join(f"- {name} — {role}" for name, _, _, role in PEOPLE.values() if role != "бухгалтерия клиентов"),
    },
    {
        "id": "s30",
        "kind": "chat",
        "project": ORB,
        "chat": "orb",
        "messages": [
            ("stepan", "2026-10-20T12:00:00+03:00", "релиз орбиты переносим на 3 декабря, отчёты не успеваем"),
        ],
    },
    {
        "id": "s31",
        "kind": "mail",
        "project": PPL,
        "thread": "ppl-release",
        "messages": [
            (
                "marina",
                ("oleg", "lapin"),
                "2026-10-22T18:00:00+03:00",
                "Релиз Пеликан-Плюс",
                "Олег, релиз Пеликан-Плюс ставим на 20 ноября, маркетплейсы предупредила.\n\nМарина",
            ),
        ],
    },
    {
        "id": "s32",
        "kind": "chat",
        "project": PEL,
        "chat": "dm-irina",
        "messages": [
            (
                "irina",
                "2026-10-23T11:00:00+03:00",
                "Олег, по пеликану 2.0: релиз 27 ноября, раньше не выйдет, трекинг ещё сыроват",
            ),
            ("oleg", "2026-10-23T11:05:00+03:00", "ок, 27-го так 27-го"),
        ],
    },
    {
        "id": "s33",
        "kind": "chat",
        "project": PEL,
        "chat": "pel-dev",
        "messages": [
            (
                "laptev",
                "2026-10-05T10:00:00+03:00",
                "ключ от api.pelican-pay.example перевыпустили, новый лежит в хранилище секретов у Павла",
            ),
            ("pavel", "2026-10-05T10:30:00+03:00", "да, и ключ от переговорки на 3 этаже теперь у охраны, не у меня"),
        ],
    },
]

# rule id: the active source, the sources it replaced, topic, look-alike value, patterns
RULES: dict[str, dict[str, Any]] = {
    "R1": {
        "source": "s02",
        "replaces": ["s01"],
        "topic": "таймаут внешних запросов",
        "value": r"\b8\s*(секунд|сек\b|с\b|s\b|seconds?)|восем\w* секунд|\beight\b",
        "old": r"\b25\s*(секунд|сек\b|с\b|s\b|seconds?)|двадцат\w* пят",
        "lookalike": True,
    },
    "R2": {
        "source": "s04",
        "replaces": [],
        "topic": "число попыток",
        "value": r"всего три попытки|\b3\s*(попыт|attempts?)|three attempts",
        "old": None,
        "lookalike": True,
    },
    "R3": {
        "source": "s06",
        "replaces": [],
        "topic": "паузы между повторами",
        "value": r"2, 4, 8|вдвое",
        "old": None,
        "lookalike": False,
    },
    "R4": {
        "source": "s08",
        "replaces": ["s07"],
        "topic": "разрешённые внешние хосты",
        "value": r"api\.pelican-pay\.example",
        "old": r"geo\.partner\.example",
        "lookalike": True,
    },
    "R5": {
        "source": "s11",
        "replaces": ["s10"],
        "topic": "формат дат и разделитель CSV",
        "value": r"ДД\.ММ\.ГГГГ|DD\.MM\.YYYY|точк\w* с запятой|semicolon",
        "old": r"ГГГГ-ММ-ДД|YYYY-MM-DD",
        "lookalike": True,
    },
    "R6": {
        "source": "s13",
        "replaces": [],
        "topic": "строк в файле выгрузки",
        "value": r"\b2\s?000\b",
        "old": None,
        "lookalike": True,
    },
    "R7": {
        "source": "s15",
        "replaces": ["s14"],
        "topic": "почта в выгрузке",
        "value": r"\*\*\*@|три звёздочк|три звездочк|three asterisks",
        "old": r"финотдел",
        "lookalike": True,
    },
    "R8": {
        "source": "s18",
        "replaces": ["s17"],
        "topic": "тихие часы уведомлений",
        "value": r"21:00",
        "old": r"23:00",
        "lookalike": False,
    },
    "R9": {
        "source": "s20",
        "replaces": [],
        "topic": "срок хранения выгрузок",
        "value": r"сорок пять дней|\b45\s*(дн|days?)",
        "old": None,
        "lookalike": False,
    },
}

UNKNOWN_SENTINEL = "UNKNOWN"
MODULE_ROOT = "pelican"

PROJECT_FILES: dict[str, str] = {
    "pelican/__init__.py": "",
    "pelican/unknown.py": (
        '"""Значение, для которого в проекте нет действующего правила."""\n\n\n'
        "class _Unknown:\n"
        "    def __repr__(self) -> str:\n"
        '        return "UNKNOWN"\n\n\n'
        "UNKNOWN = _Unknown()\n\n\n"
        "class UnknownRule(Exception):\n"
        '    """Функция не может ответить: правило неизвестно."""\n'
    ),
    "README.md": (
        "# Пеликан\n\nСервис отслеживания посылок. Политики сервиса живут в модулях `pelican/*_policy.py`.\n"
        "Значение без действующего правила проекта — `UNKNOWN` из `pelican.unknown`, функция без правила "
        "бросает `UnknownRule`.\n"
    ),
}

COMMON_RULES = (
    "Правила:\n"
    "- Значения бери только из действующих решений проекта «Пеликан». Решения других проектов к нему не относятся.\n"
    "- Если решение заменено или отменено, действует последнее.\n"
    "- Если действующего решения для значения нет, присвой `UNKNOWN` из `pelican.unknown`; функция, которой нужно "
    "такое значение, бросает `UnknownRule`. Не придумывай значения.\n"
    "- Для каждого значения из решений напиши строку в `SOURCES.md`: `ИМЯ = значение — откуда (чат, письмо, "
    "встреча, заметка или документ), дата ГГГГ-ММ-ДД, кто решил`.\n"
    "- Только стандартная библиотека Python. Тесты не пиши, ничего не запускай по сети.\n"
)

# A check: id, rule, expression, expected, the stale value (old version) and the look-alike value, when they differ.
TASKS: list[dict[str, Any]] = [
    {
        "id": "t1",
        "module": "pelican.http_policy",
        "path": "pelican/http_policy.py",
        "intro": "Сделай `pelican/http_policy.py` для «Пеликана»: сколько ждать ответа внешнего сервиса, сколько раз "
        "повторять запрос, какие паузы держать и куда вообще можно ходить.",
        "spec": (
            "Модуль должен определить:\n"
            "- `TIMEOUT_SECONDS`: таймаут внешнего запроса в секундах (число).\n"
            "- `MAX_ATTEMPTS`: сколько всего попыток на запрос, считая первую.\n"
            "- `should_retry(attempts_made: int) -> bool`: можно ли сделать ещё попытку после `attempts_made` "
            "неудачных.\n"
            "- `backoff_seconds(retry: int) -> float`: пауза перед повтором номер `retry` (1 — первый повтор).\n"
            "- `is_allowed_host(host: str) -> bool`: можно ли сервису ходить на этот хост.\n"
            "- `MAX_RESPONSE_BYTES`: предельный размер ответа в байтах.\n"
            "- `LOG_RETENTION_DAYS`: сколько дней храним логи HTTP-клиента.\n"
            "- `CIRCUIT_BREAKER_ERRORS`: после скольких ошибок подряд перестаём ходить в сервис.\n"
        ),
        "known": [
            ("t1.k01", "R1", "TIMEOUT_SECONDS", 8, 25, 15),
            ("t1.k02", "R2", "MAX_ATTEMPTS", 3, None, 5),
            ("t1.k03", "R2", "should_retry(2)", True, None, None),
            ("t1.k04", "R2", "should_retry(3)", False, None, True),
            ("t1.k05", "R3", "backoff_seconds(1)", 2.0, None, None),
            ("t1.k06", "R3", "backoff_seconds(2)", 4.0, None, None),
            ("t1.k07", "R3", "backoff_seconds(3)", 8.0, None, None),
            ("t1.k08", "R4", "is_allowed_host('api.pelican-pay.example')", True, None, False),
            ("t1.k09", "R4", "is_allowed_host('geo.partner.example')", False, True, None),
            ("t1.k10", "R4", "is_allowed_host('api.pp-pay.example')", False, None, True),
        ],
        "unknown": [
            ("t1.u01", "MAX_RESPONSE_BYTES", None, None),
            ("t1.u02", "LOG_RETENTION_DAYS", "s22", 14),
            ("t1.u03", "CIRCUIT_BREAKER_ERRORS", "s23", 5),
        ],
    },
    {
        "id": "t2",
        "module": "pelican.export_policy",
        "path": "pelican/export_policy.py",
        "intro": "Сделай `pelican/export_policy.py` для «Пеликана»: как писать даты и поля в CSV-выгрузке клиентов, "
        "сколько строк класть в файл, что делать с почтой и сколько хранить файлы.",
        "spec": (
            "Модуль должен определить:\n"
            "- `DELIMITER`: разделитель полей, строкой из одного символа.\n"
            "- `format_date(value: datetime.date) -> str`: дата в формате выгрузки.\n"
            "- `render_row(fields: list[str]) -> str`: одна строка CSV без перевода строки, без кавычек.\n"
            "- `MAX_ROWS`: сколько строк данных в одном файле.\n"
            "- `split_counts(total: int) -> list[int]`: сколько строк в каждом файле по порядку.\n"
            "- `part_name(number: int) -> str`: имя файла номер `number` без расширения.\n"
            "- `mask_email(address: str) -> str`: адрес почты в том виде, в каком он попадает в выгрузку.\n"
            "- `INCLUDE_FULL_EMAIL`: отдаём ли адрес почты целиком (bool).\n"
            "- `EXPORT_RETENTION_DAYS`: сколько дней храним файлы выгрузки.\n"
            "- `FILE_ENCODING`: кодировка файлов выгрузки.\n"
            "- `COMPRESSION`: как сжимаем файлы, строкой.\n"
            "- `SORT_FIELD`: поле, по которому сортируем строки.\n"
        ),
        "known": [
            ("t2.k01", "R5", "DELIMITER", ";", ",", "\t"),
            ("t2.k02", "R5", "format_date(datetime.date(2026, 3, 5))", "05.03.2026", "2026-03-05", "2026-03-05"),
            ("t2.k03", "R5", "render_row(['a', 'b'])", "a;b", "a,b", "a\tb"),
            ("t2.k04", "R5", "render_row(['1', '2', '3'])", "1;2;3", "1,2,3", "1\t2\t3"),
            ("t2.k05", "R6", "MAX_ROWS", 2000, None, 10000),
            ("t2.k06", "R6", "split_counts(4500)", [2000, 2000, 500], None, [4500]),
            ("t2.k07", "R6", "part_name(2)", "part-2", None, None),
            (
                "t2.k08",
                "R7",
                "mask_email('ivan.petrov@mail.example')",
                "i***@mail.example",
                "ivan.petrov@mail.example",
                "ivan.petrov@mail.example",
            ),
            ("t2.k09", "R7", "INCLUDE_FULL_EMAIL", False, True, True),
            ("t2.k10", "R9", "EXPORT_RETENTION_DAYS", 45, None, None),
        ],
        "unknown": [
            ("t2.u01", "FILE_ENCODING", "s24", "cp1251"),
            ("t2.u02", "COMPRESSION", None, None),
            ("t2.u03", "SORT_FIELD", "s25", None),
        ],
    },
    {
        "id": "t3",
        "module": "pelican.notify_policy",
        "path": "pelican/notify_policy.py",
        "intro": "Сделай `pelican/notify_policy.py` для «Пеликана»: когда клиентам нельзя слать уведомления, сколько "
        "можно в сутки и как ходить на вебхук доставки.",
        "spec": (
            "Модуль должен определить:\n"
            "- `QUIET_START` и `QUIET_END`: начало и конец окна тишины, строкой `ЧЧ:ММ`.\n"
            "- `QUIET_TIMEZONE`: часовой пояс окна тишины, имя IANA.\n"
            "- `in_quiet_hours(moment: datetime.datetime) -> bool`: попадает ли момент (с часовым поясом) в окно "
            "тишины.\n"
            "- `WEBHOOK_TIMEOUT_SECONDS`: таймаут запроса к вебхуку в секундах (вебхук — внешний запрос).\n"
            "- `WEBHOOK_MAX_ATTEMPTS`: сколько всего попыток доставки на вебхук, считая первую.\n"
            "- `webhook_host_allowed(host: str) -> bool`: можно ли слать вебхук на этот хост.\n"
            "- `MAX_PER_DAY`: сколько уведомлений одному клиенту в сутки, не больше.\n"
            "- `CHANNEL`: канал уведомлений, строкой.\n"
            "- `ESCALATION_MINUTES`: через сколько минут без ответа передаём клиента оператору.\n"
        ),
        "known": [
            ("t3.k01", "R8", "QUIET_START", "21:00", "23:00", None),
            ("t3.k02", "R8", "QUIET_END", "09:00", "07:00", None),
            ("t3.k03", "R8", "QUIET_TIMEZONE", "Europe/Moscow", None, None),
            ("t3.k04", "R8", "in_quiet_hours(msk(20, 59))", False, None, None),
            ("t3.k05", "R8", "in_quiet_hours(msk(22, 0))", True, False, None),
            ("t3.k06", "R8", "in_quiet_hours(msk(8, 0))", True, False, None),
            ("t3.k07", "R8", "in_quiet_hours(msk(9, 0))", False, None, None),
            ("t3.k08", "R1", "WEBHOOK_TIMEOUT_SECONDS", 8, 25, 15),
            ("t3.k09", "R2", "WEBHOOK_MAX_ATTEMPTS", 3, None, 5),
            ("t3.k10", "R4", "webhook_host_allowed('geo.partner.example')", False, True, None),
        ],
        "unknown": [
            ("t3.u01", "MAX_PER_DAY", "s21", 3),
            ("t3.u02", "CHANNEL", "s26", "sms"),
            ("t3.u03", "ESCALATION_MINUTES", None, None),
        ],
    },
]

# Markers of the deleted note and the revoked folder: neither may reach the model after the change.
MARKERS = {"deleted": "ЗЕЛЁНЫЙ-КАКТУС-41", "revoked": "СИНИЙ-ЁЖ-17"}
