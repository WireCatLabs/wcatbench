"""Background sources: everyday company talk in the same kinds and style as the rule sources, with no task value.

Shares follow the round config: 30% name «Пеликан», 25% «Пеликан-Плюс», 20% «Орбита», 25% no project; 40% touch a
rule topic without the task's value, and a tenth of those carry a value for another project or service. Each text
is checked against every rule pattern and marker, so noise can never answer a check.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timedelta
from typing import Any

from wcatbench.datasets.company_round import content

PROJECT_SHARES = ((content.PEL, 30), (content.PPL, 25), (content.ORB, 20), (content.NONE, 25))
TOPIC_SHARE = 0.4
VALUE_SHARE = 0.1
KINDS = (("chat", 60), ("mail", 20), ("note", 10), ("meeting", 5), ("doc", 5))
START = datetime(2026, 1, 12, 9, 0)
DAYS = 310

NAME = {
    content.PEL: ("Пеликан", "пеликан", "пеликане", "пеликана", "пеликану"),
    content.PPL: ("Пеликан-Плюс", "ПП", "плюсе", "плюса", "ПП"),
    content.ORB: ("Орбита", "орбита", "орбите", "орбиты", "орбите"),
    content.NONE: ("офис", "офис", "офисе", "офиса", "офису"),
}

EVERYDAY = [
    "в {p2} опять упал деплой, {who} смотрит",
    "кто сегодня дежурит по {p4}?",
    "созвон по {p4} переносим на {hour}:30",
    "залил фикс в {p1}, гляньте ревью плиз",
    "в {p2} тормозит страница трекинга, вечером разберусь",
    "{who}, скинь макеты для {p3}",
    "по {p4} есть новые баги от поддержки, завёл {n} задач",
    "у кого доступ к логам {p3}? нужно глянуть одну ошибку",
    "завтра меня не будет до обеда, по {p4} пишите {who}",
    "обновил зависимости в {p2}, всё зелёное",
    "в {p2} тесты флапают, кто-нибудь видел?",
    "напоминаю про демо {p3} в пятницу",
    "кофемашина на кухне снова сломалась",
    "кто заказывал пиццу на {hour}?",
    "в пятницу корпоратив, отметьтесь в таблице",
    "поменял пароль от вайфая в переговорке, спросите у {who}",
    "{who}, глянь мой PR в {p2}, там мелочь",
    "клиент {p3} спрашивает про статус заявки, кто в курсе?",
    "оценка по задаче в {p2} — {n} дня, не меньше",
    "в {p2} поправил опечатку в письме клиенту",
]

TOPICAL = [
    "надо бы пересмотреть таймауты в {p2}, но это не срочно",
    "кто помнит, где у нас настройки ретраев для {p3}?",
    "по формату выгрузок в {p2} есть вопросы от поддержки, обсудим на синке",
    "сколько мы храним логи {p3}? не нашёл в вики",
    "тихие часы уведомлений в {p2} работают? клиент жаловался",
    "в {p2} кто-то менял белый список хостов? проверю потом",
    "посмотрите, как маскируется почта в отчётах {p3}, мне кажется криво",
    "лимит строк в выгрузке {p3} мешает аналитикам, подумаем",
    "сколько попыток у вебхука в {p2}? надо проверить",
    "паузы между повторами в {p2} надо бы вынести в конфиг",
]

VALUED = [
    "в {other} таймаут на выгрузку отчётов {sec} секунд",
    "{other}: логи храним {days} дней",
    "{other} отдаёт выгрузки в формате {fmt}",
    "в {other} не больше {rows} строк в отчёте",
    "у {other} размыкаем цепь после {errors} ошибок подряд",
    "{other}: уведомления шлём не чаще {per_day} раз в неделю",
]

OTHERS = {
    content.PPL: ("ПП", "Пеликан-Плюс"),
    content.ORB: ("Орбита", "отчётах Орбиты"),
    content.NONE: ("интеграция с 1С", "сервис рассылок"),
}

MAIL_SUBJECTS = [
    "{p1}: итоги недели",
    "Счёт за хостинг",
    "{p1}: доступы для нового сотрудника",
    "Отпуск в {month}",
    "{p1}: вопрос от клиента",
    "Планирование спринта",
    "{p1}: отчёт поддержки",
]
MEETINGS = ["{p1} — планирование", "{p1} — дейли", "Общий созвон", "{p1} — разбор багов"]
MONTHS = ["январе", "феврале", "марте", "апреле", "мае", "июне", "июле", "августе", "сентябре", "октябре"]
CLOSERS = ["", "", " спасибо", " 🙏", " если что пишите", ")"]

# Every pattern a check reads, and the markers: noise must never carry them.
BANNED = (
    [pattern for rule in content.RULES.values() for pattern in (rule["value"], rule["old"]) if pattern]
    + [re.escape(marker) for marker in content.MARKERS.values()]
    + [r"api\.pp-pay", r"\b15\s*секунд", r"cp1251"]
)


def typo(text: str, rng: random.Random) -> str:
    """One dropped or swapped letter in a word of 5 or more letters, as people type in chats."""
    words = text.split(" ")
    long = [i for i, word in enumerate(words) if len(word) >= 5 and word.isalpha()]
    if not long:
        return text
    at = rng.choice(long)
    word = words[at]
    cut = rng.randrange(1, len(word) - 1)
    words[at] = (
        word[:cut] + word[cut + 1 :]
        if rng.random() < 0.5
        else word[: cut - 1] + word[cut] + word[cut - 1] + word[cut + 1 :]
    )
    return " ".join(words)


def pick(rng: random.Random, weighted: tuple[tuple[str, int], ...]) -> str:
    return rng.choices([item for item, _ in weighted], [weight for _, weight in weighted])[0]


def line(rng: random.Random, project: str) -> str:
    names = NAME[project]
    slots = {
        "p1": names[0],
        "p2": names[2],
        "p3": names[3],
        "p4": names[4],
        "who": rng.choice([name.split()[0] for name, *_ in content.PEOPLE.values()]),
        "hour": rng.randrange(10, 19),
        "n": rng.randrange(2, 9),
        "month": rng.choice(MONTHS),
    }
    roll = rng.random()
    if roll < TOPIC_SHARE * VALUE_SHARE and project != content.PEL:
        other = rng.choice(OTHERS[project])
        return rng.choice(VALUED).format(
            other=other,
            sec=rng.choice([30, 40, 60, 90]),
            days=rng.choice([10, 21, 60, 90]),
            fmt=rng.choice(["JSON", "XML", "xlsx"]),
            rows=rng.choice([500, 5000, 50000]),
            errors=rng.choice([7, 10]),
            per_day=rng.choice([2, 4]),
        )
    if roll < TOPIC_SHARE:
        return rng.choice(TOPICAL).format(**slots)
    return rng.choice(EVERYDAY).format(**slots)


def clean(text: str) -> bool:
    return not any(re.search(pattern, text, re.IGNORECASE) for pattern in BANNED)


def chat_of(project: str) -> str:
    return {content.PEL: "pel-dev", content.PPL: "ppl-dev", content.ORB: "orb", content.NONE: "office"}[project]


def people_of(chat: str) -> tuple[str, ...]:
    return content.CHATS[chat][2]


def stamp(rng: random.Random) -> str:
    moment = START + timedelta(days=rng.randrange(DAYS), minutes=rng.randrange(0, 9 * 60))
    return moment.strftime("%Y-%m-%dT%H:%M:00+03:00")


def text_of(rng: random.Random, project: str, lines: int) -> str:
    out: list[str] = []
    while len(out) < lines:
        candidate = line(rng, project)
        if clean(candidate):
            out.append(candidate)
    return out[0] if lines == 1 else "\n".join(out)


def source(index: int, rng: random.Random) -> dict[str, Any]:
    project = pick(rng, PROJECT_SHARES)
    kind = pick(rng, KINDS)
    sid = f"n{index:05d}"
    at = stamp(rng)
    if kind == "chat":
        chat = chat_of(project)
        sender = rng.choice(people_of(chat))
        text = text_of(rng, project, 1) + rng.choice(CLOSERS)
        if rng.random() < 0.3:
            text = typo(text, rng)
        return {
            "id": sid,
            "kind": "chat",
            "project": project,
            "chat": chat,
            "noise": True,
            "messages": [(sender, at, text)],
        }
    if kind == "mail":
        sender, receiver = rng.sample([p for p in content.PEOPLE if p != content.OWNER], 2)
        subject = rng.choice(MAIL_SUBJECTS).format(p1=NAME[project][0], month=rng.choice(MONTHS))
        body = f"Привет!\n\n{text_of(rng, project, 2)}\n\n{content.PEOPLE[sender][0].split()[0]}"
        return {
            "id": sid,
            "kind": "mail",
            "project": project,
            "thread": sid,
            "noise": True,
            "messages": [(sender, (receiver, content.OWNER), at, subject, body)],
        }
    if kind == "note":
        title = f"{NAME[project][0]}: заметки {at[:10]}"
        folder = NAME[project][0] if project != content.NONE else "Разное"
        return {
            "id": sid,
            "kind": "note",
            "project": project,
            "folder": "notes",
            "noise": True,
            "path": f"{folder}/{sid}.md",
            "at": at,
            "author": content.OWNER,
            "body": f"# {title}\n\n{text_of(rng, project, 3)}",
        }
    if kind == "meeting":
        speakers = rng.sample(list(people_of(chat_of(project))), 3)
        cues = [(speaker, text_of(rng, project, 1).capitalize() + ".") for speaker in speakers * 2]
        return {
            "id": sid,
            "kind": "meeting",
            "project": project,
            "noise": True,
            "title": rng.choice(MEETINGS).format(p1=NAME[project][0]),
            "at": at,
            "cues": cues,
        }
    return {
        "id": sid,
        "kind": "doc",
        "project": project,
        "noise": True,
        "path": f"{NAME[project][0]} — {sid}.md",
        "at": at,
        "author": rng.choice(list(content.PEOPLE)),
        "title": f"{NAME[project][0]}: рабочие записи",
        "body": f"# {NAME[project][0]}: рабочие записи\n\n{text_of(rng, project, 4)}",
    }


def sources(count: int, seed: int) -> list[dict[str, Any]]:
    """The same seed gives the same first sources at every size: 10x holds 1x's noise, 100x holds 10x's."""
    rng = random.Random(seed)  # noqa: S311  # nosec B311
    return [source(index, rng) for index in range(1, count + 1)]
