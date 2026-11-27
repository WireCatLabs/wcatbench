"""Experiment 2 of the rules-trial round: rules learned from a conversation, three sessions per scenario.

Session A states the rules in the conversation and corrects one of them. Session B continues the work from memory
and cancels an exception. Session C starts a new task with no transcript and must apply what is in force. Every
session starts from the clean project: the rules reach B and C only through the variant's memory.

A check's `origin` is the session whose conversation gave its value. In B and C, a check with an earlier origin is a
transfer check; `old` marks a check that fails when the agent keeps the version a later message replaced.
"""

from __future__ import annotations

from typing import Any

SESSIONS = ("A", "B", "C")

RULES = (
    "Правила:\n"
    "- Значения бери только из того, что решили в этом проекте. Если что-то заменили или отменили, действует "
    "последнее.\n"
    "- Если решения для значения нет, присвой `UNKNOWN` из `sokol.unknown`; функция, которой нужно такое значение, "
    "бросает `UnknownRule`. Не придумывай значения.\n"
    "- Только стандартная библиотека Python. Тесты не пиши, ничего не запускай по сети.\n"
)


def known(cid: str, expr: str, expected: Any, origin: str, old: bool = False) -> dict[str, Any]:
    return {"id": cid, "kind": "known", "expr": expr, "expected": expected, "origin": origin, "old": old}


def unknown(cid: str, expr: str) -> dict[str, Any]:
    return {"id": cid, "kind": "unknown", "expr": expr, "expected": "UNKNOWN", "origin": None, "old": False}


SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "w",
        "topic": "вебхуки «Сокола»",
        "sessions": {
            "A": {
                "module": "sokol.webhook_policy",
                "task": (
                    "Сделай модуль `sokol/webhook_policy.py` с политикой доставки вебхуков партнёрам «Сокола».\n\n"
                    "Модуль должен определить:\n"
                    "- `TIMEOUT_SECONDS`: сколько секунд ждём ответа партнёра.\n"
                    "- `MAX_ATTEMPTS`: сколько всего попыток доставки, считая первую.\n"
                    "- `RETRY_DELAYS`: кортеж пауз в секундах перед повторами, по порядку.\n"
                    "- `SIGNATURE_HEADER`: имя заголовка с подписью.\n"
                    "- `needs_signature(partner: str) -> bool`: нужна ли подпись для этого партнёра.\n"
                    "- `MAX_PAYLOAD_BYTES`: предельный размер тела вебхука.\n"
                    "- `DEAD_LETTER_QUEUE`: имя очереди для недоставленных вебхуков.\n"
                ),
                "dialogue": [
                    "Договорились так: ждём ответа партнёра 10 секунд, всего 5 попыток доставки, паузы перед "
                    "повторами 1, 5 и 30 секунд. Подпись кладём в заголовок X-Signature. Партнёру acme пока "
                    "разрешаем вебхуки без подписи, остальным подпись нужна всегда.",
                    "Поправка к моему сообщению: заголовок подписи не X-Signature, а X-Sokol-Signature. Старое имя "
                    "конфликтует с прокси.",
                ],
                "checks": [
                    known("w.A.k1", "TIMEOUT_SECONDS", 10, "A"),
                    known("w.A.k2", "MAX_ATTEMPTS", 5, "A"),
                    known("w.A.k3", "RETRY_DELAYS", [1, 5, 30], "A"),
                    known("w.A.k4", "SIGNATURE_HEADER", "X-Sokol-Signature", "A", old=True),
                    known("w.A.k5", "needs_signature('acme')", False, "A"),
                    known("w.A.k6", "needs_signature('globex')", True, "A"),
                    unknown("w.A.u1", "MAX_PAYLOAD_BYTES"),
                    unknown("w.A.u2", "DEAD_LETTER_QUEUE"),
                ],
            },
            "B": {
                "module": "sokol.webhook_sender",
                "task": (
                    "Продолжаем работу над вебхуками «Сокола» с прошлого разговора. Сделай модуль "
                    "`sokol/webhook_sender.py` для отправителя вебхуков.\n\n"
                    "Модуль должен определить:\n"
                    "- `TIMEOUT_SECONDS`, `MAX_ATTEMPTS`, `RETRY_DELAYS`, `SIGNATURE_HEADER`: как договорились "
                    "раньше.\n"
                    "- `needs_signature(partner: str) -> bool`: нужна ли подпись для этого партнёра.\n"
                    "- `MAX_CONCURRENT`: сколько доставок идёт одновременно.\n"
                    "- `MAX_PAYLOAD_BYTES`: предельный размер тела вебхука.\n"
                    "- `DEAD_LETTER_QUEUE`: имя очереди для недоставленных вебхуков.\n"
                ),
                "dialogue": [
                    "Исключение для acme отменяем: с этого дня подпись нужна всем партнёрам без исключений. И ещё: "
                    "одновременно отправляем не больше 8 доставок.",
                ],
                "checks": [
                    known("w.B.k1", "TIMEOUT_SECONDS", 10, "A"),
                    known("w.B.k2", "MAX_ATTEMPTS", 5, "A"),
                    known("w.B.k3", "RETRY_DELAYS", [1, 5, 30], "A"),
                    known("w.B.k4", "SIGNATURE_HEADER", "X-Sokol-Signature", "A", old=True),
                    known("w.B.k5", "needs_signature('acme')", True, "B", old=True),
                    known("w.B.k6", "needs_signature('globex')", True, "A"),
                    known("w.B.k7", "MAX_CONCURRENT", 8, "B"),
                    unknown("w.B.u1", "MAX_PAYLOAD_BYTES"),
                    unknown("w.B.u2", "DEAD_LETTER_QUEUE"),
                ],
            },
            "C": {
                "module": "sokol.webhook_config",
                "task": (
                    "Сделай модуль `sokol/webhook_config.py`: вся действующая конфигурация вебхуков «Сокола» в "
                    "одном месте.\n\n"
                    "Модуль должен определить:\n"
                    "- `TIMEOUT_SECONDS`: сколько секунд ждём ответа партнёра.\n"
                    "- `MAX_ATTEMPTS`: сколько всего попыток доставки, считая первую.\n"
                    "- `RETRY_DELAYS`: кортеж пауз в секундах перед повторами, по порядку.\n"
                    "- `SIGNATURE_HEADER`: имя заголовка с подписью.\n"
                    "- `needs_signature(partner: str) -> bool`: нужна ли подпись для этого партнёра.\n"
                    "- `MAX_CONCURRENT`: сколько доставок идёт одновременно.\n"
                    "- `MAX_PAYLOAD_BYTES`: предельный размер тела вебхука.\n"
                    "- `DEAD_LETTER_QUEUE`: имя очереди для недоставленных вебхуков.\n"
                    "- `RATE_LIMIT_PER_MINUTE`: сколько вебхуков в минуту шлём одному партнёру.\n"
                ),
                "dialogue": [],
                "checks": [
                    known("w.C.k1", "TIMEOUT_SECONDS", 10, "A"),
                    known("w.C.k2", "MAX_ATTEMPTS", 5, "A"),
                    known("w.C.k3", "RETRY_DELAYS", [1, 5, 30], "A"),
                    known("w.C.k4", "SIGNATURE_HEADER", "X-Sokol-Signature", "A", old=True),
                    known("w.C.k5", "needs_signature('acme')", True, "B", old=True),
                    known("w.C.k6", "needs_signature('globex')", True, "A"),
                    known("w.C.k7", "MAX_CONCURRENT", 8, "B"),
                    unknown("w.C.u1", "MAX_PAYLOAD_BYTES"),
                    unknown("w.C.u2", "DEAD_LETTER_QUEUE"),
                    unknown("w.C.u3", "RATE_LIMIT_PER_MINUTE"),
                ],
            },
        },
    },
    {
        "id": "r",
        "topic": "отчёты «Сокола»",
        "sessions": {
            "A": {
                "module": "sokol.report_policy",
                "task": (
                    "Сделай модуль `sokol/report_policy.py` с политикой хранения отчётов «Сокола».\n\n"
                    "Модуль должен определить:\n"
                    "- `RETENTION_DAYS`: сколько дней храним отчёт по умолчанию.\n"
                    "- `retention_days(department: str) -> int`: сколько дней храним отчёты этого отдела.\n"
                    "- `ARCHIVE_FORMAT`: формат файла архива, строкой.\n"
                    "- `REPORT_TIMEZONE`: часовой пояс дат в отчётах, строкой IANA.\n"
                    "- `MAX_REPORT_MB`: предельный размер одного отчёта в мегабайтах.\n"
                    "- `COMPRESSION`: чем сжимаем архив, строкой.\n"
                    "- `ENCRYPTION`: чем шифруем архив, строкой.\n"
                ),
                "dialogue": [
                    "Решили так: отчёты храним 90 дней, архив пишем в CSV, даты в отчётах по Europe/Moscow, один "
                    "отчёт не больше 50 МБ. Отделу audit отчёты храним 365 дней, это исключение.",
                    "Поправка: архив не в CSV, а в parquet. CSV для архива слишком большой.",
                ],
                "checks": [
                    known("r.A.k1", "RETENTION_DAYS", 90, "A"),
                    known("r.A.k2", "retention_days('sales')", 90, "A"),
                    known("r.A.k3", "retention_days('audit')", 365, "A"),
                    known("r.A.k4", "ARCHIVE_FORMAT.lower()", "parquet", "A", old=True),
                    known("r.A.k5", "REPORT_TIMEZONE", "Europe/Moscow", "A"),
                    known("r.A.k6", "MAX_REPORT_MB", 50, "A"),
                    unknown("r.A.u1", "COMPRESSION"),
                    unknown("r.A.u2", "ENCRYPTION"),
                ],
            },
            "B": {
                "module": "sokol.report_cleanup",
                "task": (
                    "Продолжаем работу над отчётами «Сокола» с прошлого разговора. Сделай модуль "
                    "`sokol/report_cleanup.py` для ночной очистки старых отчётов.\n\n"
                    "Модуль должен определить:\n"
                    "- `RETENTION_DAYS`, `ARCHIVE_FORMAT`, `REPORT_TIMEZONE`, `MAX_REPORT_MB`: как договорились "
                    "раньше.\n"
                    "- `retention_days(department: str) -> int`: сколько дней храним отчёты этого отдела.\n"
                    "- `CLEANUP_HOUR`: в котором часу ночи по времени отчётов идёт очистка.\n"
                    "- `COMPRESSION`: чем сжимаем архив, строкой.\n"
                    "- `ENCRYPTION`: чем шифруем архив, строкой.\n"
                ),
                "dialogue": [
                    "Исключение для audit отменяем: их отчёты теперь тоже живут 90 дней, как у всех. Очистку "
                    "запускаем в 3 часа ночи.",
                ],
                "checks": [
                    known("r.B.k1", "RETENTION_DAYS", 90, "A"),
                    known("r.B.k2", "retention_days('sales')", 90, "A"),
                    known("r.B.k3", "retention_days('audit')", 90, "B", old=True),
                    known("r.B.k4", "ARCHIVE_FORMAT.lower()", "parquet", "A", old=True),
                    known("r.B.k5", "REPORT_TIMEZONE", "Europe/Moscow", "A"),
                    known("r.B.k6", "MAX_REPORT_MB", 50, "A"),
                    known("r.B.k7", "CLEANUP_HOUR", 3, "B"),
                    unknown("r.B.u1", "COMPRESSION"),
                    unknown("r.B.u2", "ENCRYPTION"),
                ],
            },
            "C": {
                "module": "sokol.report_config",
                "task": (
                    "Сделай модуль `sokol/report_config.py`: вся действующая конфигурация отчётов «Сокола» в одном "
                    "месте.\n\n"
                    "Модуль должен определить:\n"
                    "- `RETENTION_DAYS`: сколько дней храним отчёт по умолчанию.\n"
                    "- `retention_days(department: str) -> int`: сколько дней храним отчёты этого отдела.\n"
                    "- `ARCHIVE_FORMAT`: формат файла архива, строкой.\n"
                    "- `REPORT_TIMEZONE`: часовой пояс дат в отчётах, строкой IANA.\n"
                    "- `MAX_REPORT_MB`: предельный размер одного отчёта в мегабайтах.\n"
                    "- `CLEANUP_HOUR`: в котором часу ночи по времени отчётов идёт очистка.\n"
                    "- `COMPRESSION`: чем сжимаем архив, строкой.\n"
                    "- `ENCRYPTION`: чем шифруем архив, строкой.\n"
                    "- `OWNER_EMAIL`: кому писать о сбоях отчётов.\n"
                ),
                "dialogue": [],
                "checks": [
                    known("r.C.k1", "RETENTION_DAYS", 90, "A"),
                    known("r.C.k2", "retention_days('sales')", 90, "A"),
                    known("r.C.k3", "retention_days('audit')", 90, "B", old=True),
                    known("r.C.k4", "ARCHIVE_FORMAT.lower()", "parquet", "A", old=True),
                    known("r.C.k5", "REPORT_TIMEZONE", "Europe/Moscow", "A"),
                    known("r.C.k6", "MAX_REPORT_MB", 50, "A"),
                    known("r.C.k7", "CLEANUP_HOUR", 3, "B"),
                    unknown("r.C.u1", "COMPRESSION"),
                    unknown("r.C.u2", "ENCRYPTION"),
                    unknown("r.C.u3", "OWNER_EMAIL"),
                ],
            },
        },
    },
]


def checks_of(scenario: str, session: str) -> list[dict[str, Any]]:
    found = next(item for item in SCENARIOS if item["id"] == scenario)
    step = found["sessions"][session]
    return [{**check, "task": f"{scenario}.{session}", "module": step["module"]} for check in step["checks"]]


def prompt_of(scenario: str, session: str) -> str:
    """The task and the lead's messages of this session, as one prompt: Hermes runs one turn per session."""
    step = next(item for item in SCENARIOS if item["id"] == scenario)["sessions"][session]
    lines = [step["task"]]
    if step["dialogue"]:
        lines.append("Сообщения тимлида в этом разговоре, по порядку:")
        lines += [f"{n}. «{message}»" for n, message in enumerate(step["dialogue"], start=1)]
    lines.append(RULES)
    return "\n".join(lines)
