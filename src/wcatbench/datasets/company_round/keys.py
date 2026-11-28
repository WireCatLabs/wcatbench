"""The question keys, written before the questions: the fact, its sources, the trap and the hard case it covers.

A second agent wrote each question from the source text and a form only; a third added the errors (questions.py).
`none` keys have no answer in the data after the deletion and the revocation: a concrete answer is confidently wrong.
"""

from __future__ import annotations

from typing import Any

# id: answer, sources, trap sources, flags, form, hard case
KEYS: dict[str, dict[str, Any]] = {
    "q01": {
        "answer": "27 ноября",
        "sources": ["s32"],
        "traps": ["s31"],
        "flags": ["lookalike"],
        "form": "3 keywords",
        "case": "the look-alike project has another release date",
    },
    "q02": {
        "answer": "8 секунд (с мая 2026; раньше было 25)",
        "sources": ["s02"],
        "traps": ["s01"],
        "flags": ["stale"],
        "form": "an unsure full sentence",
        "case": "set in chat, changed in a meeting",
    },
    "q03": {
        "answer": "3 попытки всего, считая первую",
        "sources": ["s04"],
        "traps": ["s03"],
        "flags": ["lookalike"],
        "form": "a long dictation without punctuation",
        "case": "the rule is spread over three messages",
    },
    "q04": {
        "answer": "нет, доступ к геосервису отозван в июне 2026; можно только api.pelican-pay.example",
        "sources": ["s08"],
        "traps": ["s07"],
        "flags": ["stale"],
        "form": "a sentence asking for a judgement",
        "case": "a permission cancelled in mail",
    },
    "q05": {
        "answer": "ДД.ММ.ГГГГ, поля через точку с запятой",
        "sources": ["s11"],
        "traps": ["s10"],
        "flags": ["stale", "no_project"],
        "form": "a sentence that names no project",
        "case": "set in a document, changed in a meeting; the project is implied",
    },
    "q06": {
        "answer": "2000 строк",
        "sources": ["s13"],
        "traps": ["s12"],
        "flags": ["lookalike"],
        "form": "3 keywords",
        "case": "the look-alike allows 10 000",
    },
    "q07": {
        "answer": "5 попыток на запрос в ПП, считая первую (Сергей Лапин)",
        "sources": ["s03"],
        "traps": ["s04"],
        "flags": ["person"],
        "form": "a short sentence",
        "case": "a name close to another person's (Лапин, Лаптев)",
    },
    "q08": {
        "answer": "просила хотя бы полтора месяца; решили хранить 45 дней",
        "sources": ["s20"],
        "traps": [],
        "flags": ["person"],
        "form": "a long dictation without punctuation",
        "case": "a name mangled beyond resemblance; the decision is spread over a meeting",
    },
    "q09": {
        "answer": "в хранилище секретов у Павла",
        "sources": ["s33"],
        "traps": [],
        "flags": ["two_meanings"],
        "form": "a mix of Russian and English",
        "case": "«ключ»: the API key, not the key to the meeting room",
    },
    "q10": {
        "answer": "в июне (не в июле) Анна отменила полные адреса: первая буква, три звёздочки и домен",
        "sources": ["s15"],
        "traps": ["s14"],
        "flags": ["stale", "misremembered"],
        "form": "an unsure sentence",
        "case": "the user names the wrong month",
    },
    "q11": {
        "answer": "тихие часы 21:00–09:00 Europe/Moscow; лимита в сутки сейчас нет (отменён в сентябре)",
        "sources": ["s18", "s20"],
        "traps": ["s17", "s21"],
        "flags": ["stale", "many_sources"],
        "form": "a vague list of fragments",
        "case": "two rules across chat and a meeting, one cancelled",
    },
    "q12": {
        "answer": None,
        "sources": [],
        "traps": ["s27"],
        "flags": ["none", "deleted"],
        "form": "a short question",
        "case": "the only source was deleted",
    },
    "q13": {
        "answer": None,
        "sources": [],
        "traps": ["s24"],
        "flags": ["none", "lookalike"],
        "form": "a short question",
        "case": "only the look-alike project has a value",
    },
    "q14": {
        "answer": None,
        "sources": [],
        "traps": ["s28"],
        "flags": ["none", "revoked"],
        "form": "a sentence",
        "case": "the only source is in a folder taken out of reach",
    },
    "q15": {
        "answer": "2 секунды перед первым повтором, дальше вдвое: 2, 4, 8",
        "sources": ["s06"],
        "traps": [],
        "flags": [],
        "form": "English",
        "case": "asked in another language than the data",
    },
}

# Facts asked a second time in another form; extra sessions outside the 15, scored apart.
VARIANTS = {"q02v": "q02", "q06v": "q06", "q11v": "q11", "q15v": "q15"}

# A pattern per needed source, for recall, precision and MRR: what marks the source's text in a tool's output.
PROBES = {
    "s02": r"восем\w* секунд",
    "s03": r"15 секунд|пять на запрос",
    "s04": r"всего три попытки",
    "s06": r"2, 4, 8|вдвое длиннее",
    "s08": r"api\.pelican-pay\.example",
    "s11": r"ДД\.ММ\.ГГГГ|точкой с запятой",
    "s13": r"не больше 2000 строк",
    "s15": r"три звёздочки",
    "s18": r"21:00 до 09:00",
    "s20": r"сорок пять дней|лимит в три уведомления",
    "s32": r"27 ноября",
    "s33": r"хранилище секретов",
}
