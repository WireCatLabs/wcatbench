"""The rules-trial dev set: only for tuning the unrestricted strategy prompt, never scored with the test tasks.

A different task (cache and queue policy), different rules and values, the same traps: a look-alike project, rules
replaced later, a revoked permission and names with no rule. The project files and common rules are the test set's,
so the prompt is tuned on the same kind of work without seeing a test value.
"""

from __future__ import annotations

from typing import Any

from wcatbench.datasets.rules_trial.content import (
    COMMON_RULES,
    COMPANY,
    LITE,
    PROJECT_FILES,
    SAPSAN,
    TARGET,
    UNKNOWN_SENTINEL,
)

__all__ = ["COMMON_RULES", "PROJECT_FILES", "RULES", "SOURCES", "TARGET", "TASKS", "UNKNOWN_SENTINEL"]

SOURCES: list[tuple[str, str, str, str, str, str]] = [
    (
        "d01",
        TARGET,
        "decision",
        "Ирина Козлова",
        "2026-02-03T10:00:00+03:00",
        "Сокол, кэш: ответы каталога держим в кэше 600 секунд, этого хватает для витрины.",
    ),
    (
        "d02",
        TARGET,
        "decision",
        "Ирина Козлова",
        "2026-05-19T11:30:00+03:00",
        "Сокол, поправка по кэшу каталога: 600 секунд оказалось много, цены устаревают. С сегодняшнего дня время "
        "жизни записи в кэше каталога 120 секунд.",
    ),
    ("d03", LITE, "decision", "Павел Зуев", "2026-03-11T09:00:00+03:00", "Сокол-Лайт: кэш каталога живёт 900 секунд."),
    (
        "d04",
        TARGET,
        "decision",
        "Глеб Соколов",
        "2026-04-02T15:00:00+03:00",
        "Сокол, очередь задач: задача, которую не взяли за 45 минут, считается просроченной.",
    ),
    (
        "d05",
        TARGET,
        "decision",
        "Мария Лебедева",
        "2026-03-27T12:00:00+03:00",
        "Сокол: в кэше не больше 20000 записей, самые старые вытесняем первыми.",
    ),
    (
        "d06",
        TARGET,
        "decision",
        "Анна Белова",
        "2026-02-20T10:00:00+03:00",
        "Сокол: разрешаем держать в кэше профили клиентов, чтобы личный кабинет открывался быстрее.",
    ),
    (
        "d07",
        TARGET,
        "decision",
        "Анна Белова",
        "2026-06-10T10:00:00+03:00",
        "Сокол, безопасность: разрешение кэшировать профили клиентов отзываем. Персональные данные в кэш не кладём, "
        "кэшировать можно только каталог и справочники.",
    ),
    (
        "d08",
        SAPSAN,
        "decision",
        "Глеб Соколов",
        "2026-04-15T10:00:00+03:00",
        "Сапсан: очередь задач обрабатываем в 16 потоков.",
    ),
    (
        "d09",
        TARGET,
        "decision",
        "Дмитрий Орлов",
        "2026-07-01T10:00:00+03:00",
        "Сокол: задачи из очереди разбираем в 6 потоков, больше база не тянет.",
    ),
    (
        "d10",
        LITE,
        "chat",
        "Павел Зуев",
        "2026-07-03T18:00:00+03:00",
        "Сокол-Лайт: у нас ключи кэша с префиксом lite:, если кому интересно.",
    ),
    (
        "d11",
        TARGET,
        "decision",
        "Мария Лебедева",
        "2026-04-20T10:00:00+03:00",
        "Сокол: все ключи кэша начинаются с префикса sokol:v2:, старый префикс sokol: больше не используем.",
    ),
    (
        "d12",
        COMPANY,
        "announcement",
        "Офис",
        "2026-05-05T10:00:00+03:00",
        "Для всех: в пятницу обновляем Redis на тестовых стендах, возможны перебои.",
    ),
    (
        "d13",
        TARGET,
        "chat",
        "Ирина Козлова",
        "2026-08-12T16:00:00+03:00",
        "Сокол: обсуждали, не сжать ли записи кэша. Пока ничего не решили, вернёмся позже.",
    ),
    (
        "d14",
        TARGET,
        "decision",
        "Глеб Соколов",
        "2026-03-01T10:00:00+03:00",
        "Сокол, очередь: просроченной считаем задачу, которую не взяли за 30 минут.",
    ),
]

RULES: dict[str, dict[str, Any]] = {
    "D1": {
        "source": "d02",
        "replaces": ["d01"],
        "topic": "время жизни кэша каталога",
        "value": r"\b120\s*(секунд|сек\b|с\b|s\b|seconds?)",
        "old": r"\b600\s*(секунд|сек\b|с\b|s\b|seconds?)",
    },
    "D2": {
        "source": "d04",
        "replaces": ["d14"],
        "topic": "просрочка задачи в очереди",
        "value": r"\b45\s*(минут|мин\b|minutes?)",
        "old": r"\b30\s*(минут|мин\b|minutes?)",
    },
    "D3": {"source": "d05", "replaces": [], "topic": "размер кэша", "value": r"20\s?000", "old": None},
    "D4": {
        "source": "d07",
        "replaces": ["d06"],
        "topic": "что можно кэшировать",
        "value": r"только каталог|only the catalog",
        "old": r"разрешаем держать в кэше профили|cache customer profiles",
    },
    "D5": {
        "source": "d09",
        "replaces": [],
        "topic": "потоки очереди",
        "value": r"\b6\s*(поток|workers?|threads?)",
        "old": None,
    },
    "D6": {"source": "d11", "replaces": [], "topic": "префикс ключей", "value": r"sokol:v2:", "old": None},
}

TASKS: list[dict[str, Any]] = [
    {
        "id": "d1",
        "module": "sokol.cache_policy",
        "path": "sokol/cache_policy.py",
        "intro": [
            "Сделай модуль `sokol/cache_policy.py` с политикой кэша и очереди задач сервиса «Сокол».",
            "Опиши в `sokol/cache_policy.py`, как «Сокол» кэширует данные и когда задача в очереди просрочена.",
            "Для «Сокол» нужны правила кэша и очереди в одном модуле: `sokol/cache_policy.py`.",
        ],
        "spec": (
            "Модуль должен определить:\n"
            "- `CATALOG_TTL_SECONDS`: время жизни записи каталога в кэше, секунды.\n"
            "- `MAX_CACHE_ENTRIES`: сколько записей держим в кэше.\n"
            "- `KEY_PREFIX`: префикс ключей кэша.\n"
            "- `may_cache(kind: str) -> bool`: можно ли кэшировать данные этого вида (`catalog`, `profile`).\n"
            "- `TASK_EXPIRY_MINUTES`: через сколько минут невзятая задача просрочена.\n"
            "- `QUEUE_WORKERS`: сколько потоков разбирают очередь.\n"
            "- `CACHE_COMPRESSION`: чем сжимаем записи кэша, строкой.\n"
            "- `REDIS_DB_INDEX`: номер базы Redis.\n"
        ),
        "known": [
            ("d1.k01", "D1", "CATALOG_TTL_SECONDS", 120),
            ("d1.k02", "D3", "MAX_CACHE_ENTRIES", 20000),
            ("d1.k03", "D6", "KEY_PREFIX", "sokol:v2:"),
            ("d1.k04", "D4", "may_cache('catalog')", True),
            ("d1.k05", "D4", "may_cache('profile')", False),
            ("d1.k06", "D2", "TASK_EXPIRY_MINUTES", 45),
            ("d1.k07", "D5", "QUEUE_WORKERS", 6),
        ],
        "unknown": [
            ("d1.u01", "CACHE_COMPRESSION", "d13"),
            ("d1.u02", "REDIS_DB_INDEX", None),
        ],
    }
]
