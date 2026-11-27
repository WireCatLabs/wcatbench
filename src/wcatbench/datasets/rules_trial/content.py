"""The rules-trial corpus, tasks and hidden checks, written by hand so every expected value has one source.

Target project «Сокол» has 8 active rules (R1..R8). Five of them replaced an older text: a revision (R1, R5, R8) or a
permission that was cancelled (R4, R7). Two similar projects («Сокол-Лайт», «Сапсан») set other values for the same
topics, and for topics «Сокол» never decided: a system that returns the closest text without checking the project
fills an UNKNOWN check with a concrete value.

Every pattern below is a regular expression over a store's own text. `value` patterns mark a rule's active value,
`old` patterns mark the replaced text only: the newer text never repeats them, so an old pattern in a retrieved
context means the old version is still there. English alternatives exist because a store may rewrite a record into
facts in English.
"""

from __future__ import annotations

from typing import Any

TARGET = "Сокол"
LITE = "Сокол-Лайт"
SAPSAN = "Сапсан"
COMPANY = "Компания"

# id, project, kind, author, timestamp, text
SOURCES: list[tuple[str, str, str, str, str, str]] = [
    (
        "s01",
        TARGET,
        "decision",
        "Ирина Козлова",
        "2026-03-02T10:15:00+03:00",
        "Сокол, решение по сети: таймаут для всех внешних HTTP-запросов сервиса — 30 секунд. Меньше не ставим, "
        "партнёрские API бывают медленными.",
    ),
    (
        "s02",
        TARGET,
        "decision",
        "Ирина Козлова",
        "2026-05-14T16:40:00+03:00",
        "Сокол, поправка к решению о таймаутах. Внешние HTTP-запросы теперь обрываем через 7 секунд: долгие "
        "ожидания вешали очередь заказов. Прежнее значение больше не действует.",
    ),
    (
        "s03",
        TARGET,
        "decision",
        "Олег Мартынов",
        "2026-03-10T11:00:00+03:00",
        "Сокол: исходящий запрос к внешнему сервису пробуем не больше 4 раз всего, считая первую попытку. "
        "После четвёртой неудачи запрос считается проваленным.",
    ),
    (
        "s04",
        TARGET,
        "decision",
        "Олег Мартынов",
        "2026-03-10T11:20:00+03:00",
        "Сокол: пауза перед первым повтором запроса — 1,5 секунды, каждая следующая пауза вдвое длиннее предыдущей.",
    ),
    (
        "s05",
        TARGET,
        "chat",
        "Ирина Козлова",
        "2026-02-18T09:05:00+03:00",
        "Сокол: разрешили сервису ходить в maps.partner.example за геокодированием адресов доставки.",
    ),
    (
        "s06",
        TARGET,
        "decision",
        "Анна Белова",
        "2026-06-03T13:30:00+03:00",
        "Сокол, безопасность: доступ к maps.partner.example отозван. Из внешних хостов сервису разрешён только "
        "api.sokol-pay.example, остальные запросы блокируем.",
    ),
    (
        "s07",
        TARGET,
        "decision",
        "Дмитрий Орлов",
        "2026-02-25T15:00:00+03:00",
        "Сокол, экспорт CSV: даты пишем в формате ГГГГ-ММ-ДД, поля разделяем запятой.",
    ),
    (
        "s08",
        TARGET,
        "decision",
        "Дмитрий Орлов",
        "2026-07-08T12:10:00+03:00",
        "Сокол, экспорт CSV, новое решение по просьбе бухгалтерии клиентов: даты пишем как ДД.ММ.ГГГГ, "
        "разделитель полей — точка с запятой. Старый формат больше не используем.",
    ),
    (
        "s09",
        TARGET,
        "decision",
        "Дмитрий Орлов",
        "2026-04-01T10:00:00+03:00",
        "Сокол: в одном файле экспорта не больше 5000 строк. Остаток уходит в следующие файлы: part-2, part-3 и "
        "так далее, первый файл — part-1.",
    ),
    (
        "s10",
        TARGET,
        "chat",
        "Олег Мартынов",
        "2026-03-20T17:45:00+03:00",
        "Сокол: в выгрузке клиентов можно отдавать адреса почты целиком, финансовому отделу так удобнее сверять.",
    ),
    (
        "s11",
        TARGET,
        "decision",
        "Анна Белова",
        "2026-06-03T13:45:00+03:00",
        "Сокол, безопасность: разрешение на полные адреса почты в выгрузках отозвано. Оставляем первую букву "
        "имени, затем три звёздочки и домен, например i***@mail.example.",
    ),
    (
        "s12",
        TARGET,
        "decision",
        "Ирина Козлова",
        "2026-08-19T10:30:00+03:00",
        "Сокол: уведомления клиентам не отправляем с 22:00 до 08:00 по московскому времени (Europe/Moscow). "
        "Это решение заменяет прежнее окно тишины.",
    ),
    (
        "s13",
        TARGET,
        "decision",
        "Ирина Козлова",
        "2026-04-22T18:00:00+03:00",
        "Сокол: тихие часы для уведомлений — с 23:00 до 07:00, в это время ничего не шлём.",
    ),
    (
        "s14",
        TARGET,
        "meeting",
        "Олег Мартынов",
        "2026-09-02T12:00:00+03:00",
        "Сокол, встреча: обсуждали поднять число попыток запроса до 6. Предложение отклонили, правило о попытках "
        "не меняется.",
    ),
    (
        "s15",
        TARGET,
        "chat",
        "Анна Белова",
        "2026-09-10T09:30:00+03:00",
        "Сокол: релизы выкатываем по вторникам и четвергам до обеда, в пятницу не выкатываем.",
    ),
    (
        "s16",
        TARGET,
        "decision",
        "Дмитрий Орлов",
        "2026-05-05T14:00:00+03:00",
        "Сокол: каждое изменение в коде смотрят двое ревьюеров, один из них из команды платежей.",
    ),
    (
        "s17",
        LITE,
        "decision",
        "Павел Зуев",
        "2026-03-15T10:00:00+03:00",
        "Сокол-Лайт: таймаут внешних HTTP-запросов — 12 секунд.",
    ),
    (
        "s18",
        LITE,
        "decision",
        "Павел Зуев",
        "2026-03-15T10:10:00+03:00",
        "Сокол-Лайт: запрос пробуем не больше 2 раз, без пауз между попытками.",
    ),
    (
        "s19",
        LITE,
        "decision",
        "Павел Зуев",
        "2026-04-02T11:00:00+03:00",
        "Сокол-Лайт: разрешены внешние хосты api.sokol-lite.example и maps.partner.example.",
    ),
    (
        "s20",
        LITE,
        "decision",
        "Мария Лебедева",
        "2026-04-12T15:30:00+03:00",
        "Сокол-Лайт: логи HTTP-клиента храним 14 дней, потом удаляем.",
    ),
    (
        "s21",
        LITE,
        "decision",
        "Мария Лебедева",
        "2026-04-12T15:40:00+03:00",
        "Сокол-Лайт: заголовок User-Agent у всех запросов — SokolLite/1.0.",
    ),
    (
        "s22",
        LITE,
        "decision",
        "Мария Лебедева",
        "2026-05-20T12:00:00+03:00",
        "Сокол-Лайт: файлы экспорта храним 30 дней, даты в них пишем как ММ/ДД/ГГГГ.",
    ),
    (
        "s23",
        LITE,
        "decision",
        "Павел Зуев",
        "2026-06-11T10:20:00+03:00",
        "Сокол-Лайт: уведомления клиентам отправляем только по SMS.",
    ),
    (
        "s24",
        LITE,
        "chat",
        "Павел Зуев",
        "2026-07-01T16:00:00+03:00",
        "Сокол-Лайт: в выгрузках сортируем строки по номеру заказа.",
    ),
    (
        "s25",
        SAPSAN,
        "decision",
        "Глеб Соколов",
        "2026-02-10T10:00:00+03:00",
        "Сапсан: таймаут внешних HTTP-запросов — 20 секунд.",
    ),
    (
        "s26",
        SAPSAN,
        "decision",
        "Глеб Соколов",
        "2026-02-10T10:15:00+03:00",
        "Сапсан: не больше 5 попыток на запрос, пауза перед первым повтором 0,5 секунды, каждая следующая втрое "
        "длиннее.",
    ),
    (
        "s27",
        SAPSAN,
        "decision",
        "Глеб Соколов",
        "2026-03-03T13:00:00+03:00",
        "Сапсан: после 5 ошибок подряд размыкаем цепь и минуту не ходим во внешний сервис.",
    ),
    (
        "s28",
        SAPSAN,
        "decision",
        "Елена Фомина",
        "2026-03-28T11:30:00+03:00",
        "Сапсан: файлы экспорта сохраняем в кодировке cp1251, иначе их не открывает учётная система.",
    ),
    (
        "s29",
        SAPSAN,
        "decision",
        "Елена Фомина",
        "2026-03-28T11:45:00+03:00",
        "Сапсан: в одном файле экспорта до 10000 строк, файлы сжимаем в zip.",
    ),
    (
        "s30",
        SAPSAN,
        "decision",
        "Елена Фомина",
        "2026-05-14T09:00:00+03:00",
        "Сапсан: не больше 3 уведомлений одному клиенту в сутки.",
    ),
    (
        "s31",
        SAPSAN,
        "decision",
        "Глеб Соколов",
        "2026-06-25T10:00:00+03:00",
        "Сапсан: уведомления не отправляем с 21:00 до 09:00 по времени Asia/Yekaterinburg.",
    ),
    (
        "s32",
        SAPSAN,
        "chat",
        "Елена Фомина",
        "2026-08-08T14:20:00+03:00",
        "Сапсан: если клиент не ответил на уведомление за 45 минут, передаём его оператору.",
    ),
    (
        "s33",
        COMPANY,
        "note",
        "Отдел кадров",
        "2026-01-12T09:00:00+03:00",
        "Для всех: корпоративные праздники в этом году — 1–8 января, 23 февраля, 8 марта, 1 и 9 мая.",
    ),
    (
        "s34",
        COMPANY,
        "note",
        "Офис",
        "2026-06-30T12:00:00+03:00",
        "Для всех: с 1 сентября офис переезжает на третий этаж, переговорные бронируем в календаре.",
    ),
    (
        "s35",
        COMPANY,
        "note",
        "Служба безопасности",
        "2026-02-02T10:00:00+03:00",
        "Для всех: пароли и ключи в коде не храним, только в хранилище секретов.",
    ),
    (
        "s36",
        COMPANY,
        "note",
        "Отдел кадров",
        "2026-10-01T10:00:00+03:00",
        "Для всех: в октябре обучение по безопасности, запись у руководителя команды.",
    ),
]

# Each active rule of the target: its source, the texts it replaced, and patterns for its values and old texts.
RULES: dict[str, dict[str, Any]] = {
    "R1": {
        "source": "s02",
        "replaces": ["s01"],
        "topic": "таймаут внешних HTTP-запросов",
        "value": r"\b7\s*(секунд|сек\b|с\b|s\b|seconds?)",
        "old": r"\b30\s*(секунд|сек\b|с\b|s\b|seconds?)",
    },
    "R2": {
        "source": "s03",
        "replaces": [],
        "topic": "число попыток запроса",
        "value": r"\b4\s*(раз|попыт|attempts?|times|tries)|четыр|\bfour\b",
        "old": None,
    },
    "R3": {
        "source": "s04",
        "replaces": [],
        "topic": "пауза перед повтором",
        "value": r"\b1[,.]5\s*(секунд|сек\b|с\b|s\b|seconds?)",
        "old": None,
    },
    "R4": {
        "source": "s06",
        "replaces": ["s05"],
        "topic": "разрешённые внешние хосты",
        "value": r"api\.sokol-pay\.example",
        "old": r"геокодир|geocod",
    },
    "R5": {
        "source": "s08",
        "replaces": ["s07"],
        "topic": "формат дат и разделитель CSV",
        "value": r"ДД\.ММ\.ГГГГ|DD\.MM\.YYYY",
        "old": r"ГГГГ-ММ-ДД|YYYY-MM-DD",
    },
    "R6": {"source": "s09", "replaces": [], "topic": "строк в файле экспорта", "value": r"\b5\s?000\b", "old": None},
    "R7": {
        "source": "s11",
        "replaces": ["s10"],
        "topic": "адреса почты в выгрузке",
        "value": r"\*\*\*@|три звёздочк|три звездочк|three asterisks",
        "old": r"финансов\w* отдел|finance",
    },
    "R8": {"source": "s12", "replaces": ["s13"], "topic": "тихие часы уведомлений", "value": r"22:00", "old": r"23:00"},
}

UNKNOWN_SENTINEL = "UNKNOWN"

PROJECT_FILES: dict[str, str] = {
    "sokol/__init__.py": "",
    "sokol/unknown.py": (
        '"""Значение, для которого в проекте нет действующего правила."""\n\n\n'
        "class _Unknown:\n"
        "    def __repr__(self) -> str:\n"
        '        return "UNKNOWN"\n\n\n'
        "UNKNOWN = _Unknown()\n\n\n"
        "class UnknownRule(Exception):\n"
        '    """Функция не может ответить: правило неизвестно."""\n'
    ),
    "README.md": (
        "# Сокол\n\nСервис доставки заказов. Политики сервиса живут в модулях `sokol/*_policy.py`.\n"
        "Значение без действующего правила проекта — `UNKNOWN` из `sokol.unknown`, функция без правила "
        "бросает `UnknownRule`.\n"
    ),
}

COMMON_RULES = (
    "Правила:\n"
    "- Значения бери только из действующих правил проекта «Сокол». Правила других проектов к «Сокол» не "
    "относятся.\n"
    "- Если правило заменено или отозвано, действует последнее.\n"
    "- Если действующего правила для значения нет, присвой `UNKNOWN` из `sokol.unknown`; функция, которой "
    "нужно такое значение, бросает `UnknownRule`. Не придумывай значения.\n"
    "- Только стандартная библиотека Python. Тесты не пиши, ничего не запускай по сети.\n"
)

CONTEXT_NOTE = {
    "context": "Опыт проекта, найденный в памяти, лежит в `memory/context.md`.\n",
    "archive": "Архив переписки и решений лежит в папке `archive/`, один файл на запись.\n",
    "none": "",
}

# Each task: its module, the intro (three phrasings; phrasing 0 is the one both applications reuse), the spec of
# names, the known checks and the unknown checks. A check is an expression evaluated in the module's namespace.
TASKS: list[dict[str, Any]] = [
    {
        "id": "t1",
        "module": "sokol.http_policy",
        "path": "sokol/http_policy.py",
        "intro": [
            "Сделай модуль `sokol/http_policy.py` с политикой HTTP-клиента сервиса «Сокол»: таймаут, повторы "
            "запросов, паузы между ними и разрешённые внешние хосты.",
            "Нужна политика исходящих запросов для «Сокол»: сколько ждать ответа, сколько раз повторять, какую "
            "паузу держать и куда вообще можно ходить. Положи её в `sokol/http_policy.py`.",
            "В «Сокол» клиент внешних API пока без правил. Опиши в `sokol/http_policy.py`, когда обрывать запрос, "
            "когда и через сколько повторять и какие хосты разрешены.",
        ],
        "spec": (
            "Модуль должен определить:\n"
            "- `TIMEOUT_SECONDS`: таймаут внешнего HTTP-запроса в секундах (число).\n"
            "- `MAX_ATTEMPTS`: сколько всего попыток на запрос, считая первую.\n"
            "- `should_retry(attempts_made: int) -> bool`: можно ли сделать ещё одну попытку после "
            "`attempts_made` неудачных.\n"
            "- `backoff_seconds(retry: int) -> float`: пауза перед повтором номер `retry` (1 — первый повтор).\n"
            "- `is_allowed_host(host: str) -> bool`: можно ли сервису ходить на этот хост.\n"
            "- `request_options() -> dict`: ключи `timeout` и `max_attempts`.\n"
            "- `MAX_RESPONSE_BYTES`: предельный размер ответа в байтах.\n"
            "- `USER_AGENT`: значение заголовка User-Agent.\n"
            "- `CIRCUIT_BREAKER_ERRORS`: после скольких ошибок подряд перестаём ходить в сервис.\n"
            "- `LOG_RETENTION_DAYS`: сколько дней храним логи HTTP-клиента.\n"
            "- `TLS_MIN_VERSION`: минимальная версия TLS, строкой.\n"
        ),
        "known": [
            ("t1.k01", "R1", "TIMEOUT_SECONDS", 7),
            ("t1.k02", "R2", "MAX_ATTEMPTS", 4),
            ("t1.k03", "R2", "should_retry(1)", True),
            ("t1.k04", "R2", "should_retry(3)", True),
            ("t1.k05", "R2", "should_retry(4)", False),
            ("t1.k06", "R3", "backoff_seconds(1)", 1.5),
            ("t1.k07", "R3", "backoff_seconds(2)", 3.0),
            ("t1.k08", "R3", "backoff_seconds(3)", 6.0),
            ("t1.k09", "R4", "is_allowed_host('api.sokol-pay.example')", True),
            ("t1.k10", "R4", "is_allowed_host('maps.partner.example')", False),
            ("t1.k11", "R4", "is_allowed_host('api.sokol-lite.example')", False),
            ("t1.k12", "R1", "request_options()['timeout']", 7),
            ("t1.k13", "R2", "request_options()['max_attempts']", 4),
        ],
        "unknown": [
            ("t1.u01", "MAX_RESPONSE_BYTES", None),
            ("t1.u02", "USER_AGENT", "s21"),
            ("t1.u03", "CIRCUIT_BREAKER_ERRORS", "s27"),
            ("t1.u04", "LOG_RETENTION_DAYS", "s20"),
            ("t1.u05", "TLS_MIN_VERSION", None),
        ],
    },
    {
        "id": "t2",
        "module": "sokol.export_policy",
        "path": "sokol/export_policy.py",
        "intro": [
            "Сделай модуль `sokol/export_policy.py` с политикой CSV-выгрузки клиентов «Сокол»: формат дат, "
            "разделитель, размер файлов и что делать с адресами почты.",
            "Для «Сокол» нужна политика экспорта в CSV: как писать даты, чем разделять поля, сколько строк класть "
            "в файл и можно ли отдавать почту клиентов. Положи её в `sokol/export_policy.py`.",
            "Бухгалтерия клиентов «Сокол» получает выгрузки в CSV. Опиши в `sokol/export_policy.py` формат дат и "
            "полей, нарезку на файлы и обработку адресов почты.",
        ],
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
            "- `FILE_ENCODING`: кодировка файлов выгрузки.\n"
            "- `COMPRESSION`: как сжимаем файлы, строкой.\n"
            "- `HEADER_LANGUAGE`: язык заголовков столбцов, код языка.\n"
            "- `SORT_FIELD`: поле, по которому сортируем строки.\n"
            "- `EXPORT_RETENTION_DAYS`: сколько дней храним файлы выгрузки.\n"
        ),
        "known": [
            ("t2.k01", "R5", "DELIMITER", ";"),
            ("t2.k02", "R5", "format_date(datetime.date(2026, 3, 5))", "05.03.2026"),
            ("t2.k03", "R5", "format_date(datetime.date(2026, 12, 31))", "31.12.2026"),
            ("t2.k04", "R5", "render_row(['a', 'b'])", "a;b"),
            ("t2.k05", "R5", "render_row(['1', '2', '3'])", "1;2;3"),
            ("t2.k06", "R6", "MAX_ROWS", 5000),
            ("t2.k07", "R6", "split_counts(12000)", [5000, 5000, 2000]),
            ("t2.k08", "R6", "split_counts(5000)", [5000]),
            ("t2.k09", "R6", "split_counts(5001)", [5000, 1]),
            ("t2.k10", "R6", "part_name(2)", "part-2"),
            ("t2.k11", "R6", "part_name(1)", "part-1"),
            ("t2.k12", "R7", "mask_email('ivan.petrov@mail.example')", "i***@mail.example"),
            ("t2.k13", "R7", "INCLUDE_FULL_EMAIL", False),
        ],
        "unknown": [
            ("t2.u01", "FILE_ENCODING", "s28"),
            ("t2.u02", "COMPRESSION", "s29"),
            ("t2.u03", "HEADER_LANGUAGE", None),
            ("t2.u04", "SORT_FIELD", "s24"),
            ("t2.u05", "EXPORT_RETENTION_DAYS", "s22"),
        ],
    },
    {
        "id": "t3",
        "module": "sokol.notify_policy",
        "path": "sokol/notify_policy.py",
        "intro": [
            "Сделай модуль `sokol/notify_policy.py` с политикой уведомлений клиентам «Сокол»: тихие часы и "
            "вебхуки, через которые уходят уведомления.",
            "Нужна политика уведомлений «Сокол»: когда клиентам нельзя писать и как ходить на вебхук доставки. "
            "Положи её в `sokol/notify_policy.py`.",
            "Клиенты «Сокол» жалуются на уведомления не вовремя. Опиши в `sokol/notify_policy.py` окно тишины, "
            "ограничения на отправку и правила для вебхуков.",
        ],
        "spec": (
            "Модуль должен определить:\n"
            "- `QUIET_START` и `QUIET_END`: начало и конец окна тишины, строкой `ЧЧ:ММ`.\n"
            "- `QUIET_TIMEZONE`: часовой пояс окна тишины, имя IANA.\n"
            "- `in_quiet_hours(moment: datetime.datetime) -> bool`: попадает ли момент (с часовым поясом) в окно "
            "тишины.\n"
            "- `WEBHOOK_TIMEOUT_SECONDS`: таймаут запроса к вебхуку в секундах (вебхук — внешний HTTP-запрос).\n"
            "- `WEBHOOK_MAX_ATTEMPTS`: сколько всего попыток доставки на вебхук, считая первую.\n"
            "- `webhook_host_allowed(host: str) -> bool`: можно ли слать вебхук на этот хост.\n"
            "- `MAX_PER_DAY`: сколько уведомлений одному клиенту в сутки, не больше.\n"
            "- `CHANNEL`: канал уведомлений, строкой.\n"
            "- `SENDER_NAME`: имя отправителя в уведомлении.\n"
            "- `ESCALATION_MINUTES`: через сколько минут без ответа передаём клиента оператору.\n"
            "- `BATCH_SIZE`: сколько уведомлений отправляем одной пачкой.\n"
        ),
        "known": [
            ("t3.k01", "R8", "QUIET_START", "22:00"),
            ("t3.k02", "R8", "QUIET_END", "08:00"),
            ("t3.k03", "R8", "QUIET_TIMEZONE", "Europe/Moscow"),
            ("t3.k04", "R8", "in_quiet_hours(msk(21, 59))", False),
            ("t3.k05", "R8", "in_quiet_hours(msk(22, 0))", True),
            ("t3.k06", "R8", "in_quiet_hours(msk(3, 0))", True),
            ("t3.k07", "R8", "in_quiet_hours(msk(7, 59))", True),
            ("t3.k08", "R8", "in_quiet_hours(msk(8, 0))", False),
            ("t3.k09", "R8", "in_quiet_hours(utc(19, 30))", True),
            ("t3.k10", "R1", "WEBHOOK_TIMEOUT_SECONDS", 7),
            ("t3.k11", "R2", "WEBHOOK_MAX_ATTEMPTS", 4),
            ("t3.k12", "R4", "webhook_host_allowed('api.sokol-pay.example')", True),
            ("t3.k13", "R4", "webhook_host_allowed('maps.partner.example')", False),
        ],
        "unknown": [
            ("t3.u01", "MAX_PER_DAY", "s30"),
            ("t3.u02", "CHANNEL", "s23"),
            ("t3.u03", "SENDER_NAME", None),
            ("t3.u04", "ESCALATION_MINUTES", "s32"),
            ("t3.u05", "BATCH_SIZE", None),
        ],
    },
]
