"""Version 3: the 10,000-record archive unchanged, new records appended, and 50 questions of many kinds.

Appending, not regenerating, lets a store built on version 2 take only the new records. Version 2 asked five
questions about each of ten projects; version 3 asks 21 kinds, two or three questions each (money, calendar,
people and decisions, and answers that are not recorded), and keeps nine version 2 questions to compare rounds.

Every new subject ("Amber Kite hosting agreement") appears in no version 2 record: version 2 noise already says
"the demo moved to <date>" and "Invoice <number>", which would contradict a key about a demo or an invoice.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from wcatbench.datasets.synthetic.generator import (
    ARCHIVE_PEOPLE,
    ARCHIVE_PROJECTS,
    PAIRS,
    PROJECTS,
    Row,
    _invariant,
    iso,
    source_ref,
)

V3_SEED = 20261107
AS_OF = "2026-10-20T00:00:00Z"
MADRID = ZoneInfo("Europe/Madrid")
TWINS = {"Amber Kite": "Amber Kitchen", "Hazel Bridge": "Hazel Ridge"}
CITIES = ["Lisbon", "Porto", "Lyon", "Gdansk", "Tallinn", "Ghent", "Bilbao", "Turin", "Graz", "Aarhus"]
VENUES = ["Rooftop Nine", "Old Mill Hall", "Harbour Loft", "Glasshouse", "Tram Depot", "Atrium Twelve"]
ZONES = [("New York", "America/New_York"), ("London", "Europe/London"), ("Tokyo", "Asia/Tokyo")]
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
FAMILIES = {"money": "money", "calendar": "calendar", "people": "people and decisions", "unknown": "not recorded"}

Ask = tuple[str, str, list[Any], list[str], str | None]


@dataclass
class Item:
    kind: str
    text: str
    root: Item | None = None
    day: date = date(2026, 1, 1)
    minute: int = 0
    id: str = ""


@dataclass
class Trail:
    items: list[Item] = field(default_factory=list)

    def add(self, kind: str, text: str, root: Item | None = None) -> Item:
        self.items.append(Item(kind, text, root))
        return self.items[-1]

    def thread(self, subject: str, first: str, reply: str) -> tuple[Item, Item]:
        root = self.add("mail", f"{subject}. {first}")
        return root, self.add("mail", f"Re: {subject}. {reply} > {first}", root)


def euros(amount: int, style: int) -> str:
    """Records write amounts the way people do; the key and the scorer compare the number."""
    if style == 0:
        return f"EUR {amount:,}"
    if style == 1:
        return f"€{amount:,}"
    if style == 2 and amount % 100 == 0:
        return f"{amount / 1000:g}k euros"
    return f"{amount:,} EUR".replace(",", " ")


def canonical_amount(amount: int) -> str:
    return f"EUR {amount:,}"


def stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M")


class V3:
    def __init__(self, seed: int, v2_texts: list[str]) -> None:
        self.rng = random.Random(seed)  # noqa: S311  # nosec B311
        self.v2 = "\n".join(v2_texts)
        self.trails: list[Trail] = []
        self.subjects: list[str] = []
        self.offices: dict[str, str] = {}

    def pick(self, seq: list[Any], *avoid: Any) -> Any:
        return self.rng.choice([value for value in seq if value not in avoid])

    def team(self, project: str) -> list[str]:
        return self.rng.sample(ARCHIVE_PEOPLE, 3)

    def subject(self, project: str, noun: str) -> str:
        subject = f"{project} {noun}"
        _invariant(subject not in self.v2, f"{subject!r} is new in version 3")
        self.subjects.append(subject)
        return subject

    def placed(self, trail: Trail, first: date, last: date) -> Trail:
        """Spreads a trail between two days in its own order: a reply never precedes what it answers."""
        span = (last - first).days * 60
        for item, offset in zip(trail.items, sorted(self.rng.sample(range(span), len(trail.items))), strict=True):
            item.day, item.minute = first + timedelta(days=offset // 60), 8 * 60 + offset % 60 * 12
        self.trails.append(trail)
        return trail

    def history(self) -> tuple[date, date]:
        start = date(2026, 1, 12) + timedelta(days=self.rng.randint(0, 200))
        return start, min(start + timedelta(days=self.rng.randint(25, 70)), date(2026, 10, 16))

    def recent(self) -> tuple[date, date]:
        start = date(2026, 8, 3) + timedelta(days=self.rng.randint(0, 40))
        return start, date(2026, 10, 16)

    # Money.

    def price_revised(self, project: str) -> Ask:
        subject, (a, b, c) = self.subject(project, "hosting agreement"), self.team(project)
        t, quote = Trail(), self.rng.randrange(18, 60) * 500
        revised, proposed = quote + self.rng.randrange(4, 20) * 250, quote - self.rng.randrange(2, 8) * 500
        t.add("mail", f"{subject}. {a}: the vendor quotes {euros(quote, 0)} a year; accepted for now.")
        t.add("telegram", f"{b}: could we push the {subject} down to {euros(proposed, 1)}? Only asking.")
        _, decided = t.thread(
            subject,
            f"{b}: the vendor asks to raise the price.",
            f"{a}: agreed, the {subject} is now "
            f"{euros(revised, self.rng.randrange(4))} a year. The old price no longer applies.",
        )
        t.add("meetings", f"{subject} review: {c} still mentioned {euros(quote, 2)}; corrected in the notes.")
        self.placed(t, *self.history())
        q = f"What is the current agreed yearly price of the {subject}? Answer as an amount like EUR 12,500."
        return q, canonical_amount(revised), [decided], [canonical_amount(quote), canonical_amount(proposed)], "amount"

    def paid_total(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "consulting retainer"), self.team(project)
        t, payments = Trail(), [self.rng.randrange(4, 30) * 250 for _ in range(self.rng.choice([2, 3, 3]))]
        bounced = self.rng.randrange(4, 30) * 250
        t.add("mail", f"{subject}. {a}: the retainer is paid in parts as invoices come in.")
        cited = [
            t.add("mail", f"{subject}: payment received, {euros(p, n % 4)}. Thanks, {b}.")
            for n, p in enumerate(payments)
        ]
        t.add("mail", f"{subject}: a payment of {euros(bounced, 1)} was sent but bounced; it was not received.")
        self.placed(t, *self.history())
        q = f"How much has been paid in total toward the {subject} so far? Answer as an amount like EUR 12,500."
        stale = [canonical_amount(payments[-1]), canonical_amount(sum(payments) + bounced)]
        return q, canonical_amount(sum(payments)), cited, stale, "amount"

    def balance(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "hardware order"), self.team(project)
        t, total = Trail(), self.rng.randrange(20, 80) * 500
        paid = [self.rng.randrange(2, total // 1500) * 250 for _ in range(2)]
        order = t.add("mail", f"{subject}. {a}: the order totals {euros(total, 0)}, to be paid in instalments.")
        cited = [order] + [
            t.add("notes", f"{subject} ledger: instalment of {euros(p, n + 1)} paid by {b}.")
            for n, p in enumerate(paid)
        ]
        self.placed(t, *self.history())
        q = f"How much is still owed on the {subject}? Answer as an amount like EUR 12,500."
        return q, canonical_amount(total - sum(paid)), cited, [canonical_amount(total)], "amount"

    def refund(self, project: str) -> Ask:
        subject, (a, _, _) = self.subject(project, "conference tickets"), self.team(project)
        t, cost = Trail(), self.rng.randrange(6, 30) * 150
        back = self.rng.randrange(1, cost // 300) * 150
        bought = t.add("mail", f"{subject}. {a}: bought them for {euros(cost, 0)} in total.")
        refunded = t.add("mail", f"{subject}: one attendee cancelled, the organiser refunded {euros(back, 1)}.")
        self.placed(t, *self.history())
        q = f"What did the {subject} cost in the end, after any refund? Answer as an amount like EUR 12,500."
        return q, canonical_amount(cost - back), [bought, refunded], [canonical_amount(cost)], "amount"

    def who_paid(self, project: str) -> Ask:
        subject, (a, b, c) = self.subject(project, "team retreat deposit"), self.team(project)
        t = Trail()
        t.add("telegram", f"{a}: I can pay the {subject} on my card if that helps.")
        t.add("telegram", f"{c}: or I can, whoever is faster.")
        paid = t.add("mail", f"{subject}. {b}: paid it this morning, {euros(self.rng.randrange(4, 20) * 100, 1)}.")
        self.placed(t, *self.history())
        return f"Who paid the {subject}?", b, [paid], [a, c], None

    # Calendar.

    def rescheduled(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "steering committee meeting"), self.team(project)
        t, when = Trail(), datetime(2026, 11, 2, tzinfo=MADRID) + timedelta(days=self.rng.randint(0, 40))
        when = when.replace(hour=self.rng.choice([9, 10, 11, 14, 15, 16]))
        stale, moved = [], self.rng.choice([1, 2, 2])
        t.add("mail", f"{subject}. {a}: set for {when:%A %d %B} at {when:%H:%M} Madrid time.")
        for _ in range(moved):
            stale.append(stamp(when))
            when = (when + timedelta(days=self.rng.randint(1, 9))).replace(hour=self.rng.choice([9, 11, 12, 16, 17]))
            moved_to = f"{when:%Y-%m-%d} at {when:%H:%M} (Madrid)"
            last = t.add("mail", f"{subject}. {a}: moved to {moved_to}. Calendar updated.")
        t.add("telegram", f"{b}: could we do the {subject} an hour later? No answer yet.")
        self.placed(t, *self.recent())
        q = f"When is the {subject} now? Answer as YYYY-MM-DD HH:MM in Madrid time."
        return q, stamp(when), [last], stale, "datetime"

    def time_zone(self, project: str, place: tuple[str, str] | None = None) -> Ask:
        subject, (a, b, _) = self.subject(project, "partner call"), self.team(project)
        city, zone = place or self.rng.choice(ZONES)
        day = (
            date(2026, 10, 26) + timedelta(days=self.rng.randint(0, 3))
            if place
            else date(2026, 11, 9) + timedelta(days=self.rng.randint(0, 30))
        )
        local = datetime(day.year, day.month, day.day, self.rng.choice([8, 9, 10, 16, 17]), 30, tzinfo=ZoneInfo(zone))
        madrid = local.astimezone(MADRID)
        # Europe leaves summer time on 25 October 2026, the United States on 1 November: that week Madrid is
        # 5 hours ahead of New York, not 6.
        gap = madrid.utcoffset() - local.utcoffset()  # type: ignore[operator]
        _invariant(place is None or gap == timedelta(hours=5), "the New York call falls in the 5-hour week")
        t = Trail()
        set_at = t.add("mail", f"{subject}. {b}: the partner set it for {local:%Y-%m-%d} at {local:%H:%M} {city} time.")
        t.add("telegram", f"{a}: noted the {subject}, will join from Madrid.")
        self.placed(t, *self.recent())
        q = f"When is the {subject}, in Madrid time? Answer as YYYY-MM-DD HH:MM."
        return q, stamp(madrid), [set_at], [stamp(local)], "datetime"

    def relative(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "design critique"), self.team(project)
        t = Trail()
        t.add("telegram", f"{b}: when do we hold the {subject}?")
        days = self.rng.choice([9, 10, 12, 15])
        set_at = t.add("telegram", f"{a}: let us hold the {subject} {days} days from today. Decided.")
        self.placed(t, *self.history())
        q = f"On what date is the {subject}? Answer as YYYY-MM-DD."
        return q, str(set_at.day + timedelta(days=days)), [set_at], [str(set_at.day)], "date"

    def cancelled(self, project: str) -> Ask:
        subject, (a, _, _) = self.subject(project, "customer workshop"), self.team(project)
        t, day = Trail(), date(2026, 11, 3) + timedelta(days=self.rng.randint(0, 40))
        t.add("mail", f"{subject}. {a}: booked for {day}, room and catering confirmed.")
        gone = t.add("mail", f"{subject}. {a}: cancelled, the customer withdrew. It will not take place.")
        t.add("notes", f"{subject} prep list (older copy): agenda for {day}.")
        self.placed(t, *self.recent())
        q = f"When is the {subject}? Answer as YYYY-MM-DD, or cancelled if it will not take place."
        return q, "cancelled", [gone], [str(day)], "date"

    def reinstated(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "hackathon"), self.team(project)
        t, day = Trail(), date(2026, 11, 3) + timedelta(days=self.rng.randint(0, 30))
        back = day + timedelta(days=self.rng.randint(7, 20))
        t.add("mail", f"{subject}. {a}: planned for {day}.")
        t.add("mail", f"{subject}. {a}: cancelled, no budget this quarter.")
        on = t.add("mail", f"{subject}. {b}: good news, it is back on, now on {back}. Confirmed.")
        self.placed(t, *self.recent())
        q = f"When is the {subject}? Answer as YYYY-MM-DD, or cancelled if it will not take place."
        return q, str(back), [on], ["cancelled", str(day)], "date"

    def weekday(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "weekly design sync"), self.team(project)
        old, new = self.rng.sample(WEEKDAY_NAMES, 2)
        t = Trail()
        t.add("meetings", f"{subject}: every {old} at 10:00.")
        if "Friday" not in (old, new):
            t.add("telegram", f"{b}: maybe the {subject} on Fridays instead? Just a thought.")
        moved = t.add("mail", f"{subject}. {a}: from next week the sync moves from {old} to {new}, same time.")
        self.placed(t, *self.history())
        return f"On which weekday does the {subject} take place now?", new, [moved], [old], "weekday"

    # People and decisions.

    def approver(self, project: str) -> Ask:
        subject, (a, b, c) = self.subject(project, "vendor shortlist"), self.team(project)
        t = Trail()
        t.add("mail", f"{subject}. {a}: here is my proposed list of three vendors.")
        t.add("telegram", f"{c}: I left comments on the {subject}.")
        signed = t.add("mail", f"{subject}. {b}: signed off, as head of purchasing. Go ahead.")
        self.placed(t, *self.history())
        return f"Who signed off the {subject}?", b, [signed], [a, c], None

    def conflict(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "launch party"), self.team(project)
        old, booked, rumour = self.rng.sample(VENUES, 3)
        t = Trail()
        t.add("notes", f"{subject} (planning notes): {old}, to be confirmed.")
        done = t.add("mail", f"{subject}. {a}: booked {booked}; the deposit is paid. {old} is off.")
        t.add("telegram", f"{b}: I heard it might be {rumour} after all? Not sure.")
        self.placed(t, *self.history())
        return f"Which venue is booked for the {subject}?", booked, [done], [old, rumour], None

    def moves(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "security drill"), self.team(project)
        t, day, times = Trail(), date(2026, 11, 2), self.rng.choice([2, 3, 4])
        t.add("mail", f"{subject}. {a}: scheduled for {day}.")
        cited = []
        for _ in range(times):
            day += timedelta(days=self.rng.randint(3, 10))
            cited.append(t.add("mail", f"{subject}. {a}: rescheduled to {day}."))
        t.add("telegram", f"{b}: should we move the {subject} again? Nothing decided.")
        self.placed(t, *self.recent())
        q = f"How many times has the {subject} been rescheduled? Answer with a number."
        return q, str(times), cited, [str(times + 1)], "count"

    def owner_city(self, subject: str, owner: str, former: list[str]) -> Ask:
        """Two steps: the current owner comes from the version 2 records, the city from a version 3 one."""
        _invariant(owner not in self.offices, f"{owner} has one office history")
        t = Trail()
        first, now = self.rng.sample(CITIES, 2)
        t.add("notes", f"Office list: {owner} works from the {first} office.")
        moved = t.add("mail", f"Office move. {owner}: I have moved from the {first} office to the {now} office.")
        self.offices[owner] = now
        stale = [first]
        for person in [*former, PAIRS.get(owner, "")]:
            if person and person not in self.offices:
                self.offices[person] = self.pick(CITIES, now)
                t.add("notes", f"Office list: {person} works from the {self.offices[person]} office.")
            if person and self.offices[person] != now:
                stale.append(self.offices[person])
        self.placed(t, *self.history())
        return f"In which city is the current delivery owner of the {subject} based?", now, [moved], stale, None

    # Not recorded.

    def unknown_fee(self, project: str) -> Ask:
        subject, (a, b, _) = self.subject(project, "translation vendor"), self.team(project)
        t = Trail()
        t.add("mail", f"{subject}. {a}: they ask {euros(self.rng.randrange(8, 40) * 250, 0)}; not approved yet.")
        t.add("telegram", f"{b}: any decision on the {subject}? No reply so far.")
        self.placed(t, *self.history())
        return f"What fee was approved for the {subject}?", "unknown", [], [], None


KINDS: list[tuple[str, str, Callable[..., Ask], int]] = [
    ("money", "price after a revision", V3.price_revised, 3),
    ("money", "total of partial payments", V3.paid_total, 3),
    ("money", "balance still owed", V3.balance, 3),
    ("money", "cost after a refund", V3.refund, 2),
    ("money", "who paid", V3.who_paid, 2),
    ("calendar", "meeting moved, date and time", V3.rescheduled, 3),
    ("calendar", "time zone conversion", V3.time_zone, 3),
    ("calendar", "relative date", V3.relative, 3),
    ("calendar", "cancelled", V3.cancelled, 3),
    ("calendar", "cancelled, then back on", V3.reinstated, 2),
    ("calendar", "recurring meeting, new weekday", V3.weekday, 2),
    ("people", "who signed off", V3.approver, 2),
    ("people", "two sources disagree", V3.conflict, 3),
    ("people", "how many times rescheduled", V3.moves, 2),
    ("unknown", "fee never approved", V3.unknown_fee, 2),
]
# Version 2 questions kept, by their opening words: (family, kind, how many).
KEPT = [
    ("What is the current confirmed delivery date", "people", "current date after many changes", 2),
    ("What was the original delivery date", "people", "original date", 1),
    ("Who is the confirmed delivery owner", "people", "owner after a handover", 2),
    ("What did ", "people", "revised commitment", 2),
    ("What approved budget amount", "unknown", "budget never approved", 2),
]
NOISE = [
    ("mail", "Expense report. {a}: submitted the {topic} receipts, {amount}."),
    ("telegram", "{a}: can someone approve my {topic} expense? {amount}."),
    ("mail", "Calendar. {a}: the {topic} call moved to {when}."),
    ("telegram", "{a}: running five minutes late for the {topic} call."),
    ("notes", "Reminder: pay the {topic} subscription, {amount} a month."),
    ("mail", "Room booking. {a}: booked the small room for the {topic} chat on {when}."),
    ("meetings", "{a} and {b}: talked about the {topic} costs, about {amount}; nothing decided."),
]
NOISE_TOPICS = ["parking", "coffee machine", "laptop stand", "taxi", "team lunch", "book club", "train", "hotel"]


# The paraphrased question set: the first question of each kind below asked in other words, with the project
# name kept (without it the question has no single answer) and the record's own phrase gone. The records and
# the answer key do not change, so a store built for version 3 answers both sets.
PARAPHRASES: dict[str, list[tuple[str, str]]] = {
    "price after a revision": [
        ("current agreed yearly price of the", "yearly fee we now pay for"),
        (" hosting agreement", "'s rented servers"),
    ],
    "total of partial payments": [
        ("How much has been paid in total toward the", "What sum has come in so far for"),
        (" consulting retainer so far", "'s advisory arrangement"),
    ],
    "balance still owed": [
        ("How much is still owed on the", "What is left to pay for"),
        (" hardware order", "'s equipment purchase"),
    ],
    "cost after a refund": [
        ("What did the", "What was the final spend on"),
        (" conference tickets cost in the end, after any refund", "'s event passes, money back counted"),
    ],
    "who paid": [("Who paid the", "Who put down the money for"), (" team retreat deposit", "'s offsite advance")],
    "meeting moved, date and time": [
        ("When is the", "When does"),
        (" steering committee meeting now", "'s oversight board sit next"),
    ],
    "time zone conversion": [
        ("When is the", "At what moment in Spain is"),
        (" partner call, in Madrid time", "'s conversation with the outside company"),
    ],
    "relative date": [
        ("On what date is the", "Which day was set for"),
        (" design critique", "'s feedback session on the designs"),
    ],
    "cancelled": [("When is the", "When will"), (" customer workshop", "'s client training day happen")],
    "cancelled, then back on": [("When is the", "When will"), (" hackathon", "'s coding marathon happen")],
    "recurring meeting, new weekday": [
        ("On which weekday does the", "Which day of the week is"),
        (" weekly design sync take place now", "'s regular design catch-up held on now"),
    ],
    "who signed off": [
        ("Who signed off the", "Who gave final approval to"),
        (" vendor shortlist", "'s list of candidate suppliers"),
    ],
    "two sources disagree": [
        ("Which venue is booked for the", "Where will"),
        (" launch party", "'s release celebration be held"),
    ],
    "how many times rescheduled": [
        ("How many times has the", "How often was"),
        (" security drill been rescheduled", "'s safety exercise moved"),
    ],
    "fee never approved": [
        ("What fee was approved for the", "What price did we accept from"),
        (" translation vendor", "'s localisation supplier"),
    ],
    "current date after many changes": [
        ("What is the current confirmed delivery date for the", "By when must the"),
        ("?", " be shipped now, as last agreed?"),
    ],
    "owner after a handover": [("Who is the confirmed delivery owner of the", "Which person answers for shipping the")],
    "revised commitment": [("commit to delivering for the", "promise to hand over for the")],
}


# A story's twin is told about a random other project, and with seed 20261107 that project was sometimes one the
# same kind of question asks about, so two stories share a subject. The records stay as published (stores already
# hold them); these keys are read off both stories instead. Found by the agents, which all answered these the same.
KEY_FIXES: dict[str, dict[str, Any]] = {
    # The asked story ends later, so its key holds; the twin's confirmed value is one more stale answer.
    "Juniper Valley hosting agreement": {"stale": ["EUR 27,750"]},
    "Grove Atlas hosting agreement": {"stale": ["EUR 29,000"]},
    "Grove Atlas design critique": {"stale": ["2026-04-26"]},
    # The twin was booked last: Harbour Loft, and the asked story's Old Mill Hall is now off.
    "Iris Summit launch party": {
        "answers": ["Harbour Loft"],
        "stale": ["Old Mill Hall", "Glasshouse"],
        "cite_text": "booked Harbour Loft",
    },
    # Three moves in the asked story, two in the twin, and the twin's new date for it counts as a sixth.
    "Amber Kite security drill": {"answers": ["5", "6"], "stale": ["3"], "cite_text": "rescheduled to"},
}
# Shared subjects whose questions still have one right answer: the twin never approved a fee either.
HARMLESS = {"Cedar Lantern translation vendor", "Flint Meadow translation vendor"}


def paraphrased(question: str, kind: str) -> str:
    for old, new in PARAPHRASES[kind]:
        _invariant(old in question, f"{kind}: {old!r} is in {question!r}")
        question = question.replace(old, new, 1)
    return question


def extension(
    v2_records: list[Row], v2_questions: list[Row], seed: int = V3_SEED, noise: int = 200, paraphrase: bool = False
) -> tuple[list[Row], list[Row], list[dict[str, Any]]]:
    """The records appended to version 2, the 50 questions and each question's family and kind."""
    v3 = V3(seed, [record["text"] for record in v2_records])
    rng = v3.rng
    asks: list[tuple[str, str, Ask]] = []
    projects = iter(rng.sample(PROJECTS, len(PROJECTS)) * 10)
    for family, kind, build, count in KINDS:
        chosen = [next(projects) for _ in range(count)]
        for n, project in enumerate(chosen):
            extra = {"place": ("New York", "America/New_York")} if build is V3.time_zone and n == 0 else {}
            asks.append((family, kind, build(v3, project, **extra)))
            # The same story about a twin or another project, with other values and never asked.
            build(v3, TWINS.get(project) or v3.pick(ARCHIVE_PROJECTS, project), **extra)
    by_prefix = {prefix: [row for row in v2_questions if row["question"].startswith(prefix)] for prefix, *_ in KEPT}
    # A kept question about a change is one where the change happened: a handover, a revised commitment.
    changed = ("What is the current", "Who is the confirmed", "What did ")
    for prefix, family, kind, count in KEPT:
        rows = [row for row in by_prefix[prefix] if row["stale_answers"] or not prefix.startswith(changed)]
        for row in rng.sample(rows, count):
            ask = (row["question"], row["answers"][0], list(row["required_citations"]), row["stale_answers"], None)
            asks.append((family, kind, ask))
    kept = {ask[0] for _, _, ask in asks}
    owners = [row for row in by_prefix["Who is the confirmed delivery owner"] if row["question"] not in kept]
    taken = 0
    for row in rng.sample(owners, len(owners)):
        if taken == 3 or row["answers"][0] in v3.offices:
            continue
        subject = row["question"].removeprefix("Who is the confirmed delivery owner of the ").removesuffix("?")
        asks.append(
            ("people", "two steps: owner, then city", v3.owner_city(subject, row["answers"][0], row["stale_answers"]))
        )
        taken += 1

    noise_trail = Trail()
    for _ in range(noise):
        kind, template = rng.choice(NOISE)
        a, b = rng.sample(ARCHIVE_PEOPLE, 2)
        when = date(2026, 1, 12) + timedelta(days=rng.randint(0, 300))
        amount = euros(rng.randrange(1, 400) * 5, rng.randrange(4))
        noise_trail.add(kind, template.format(a=a, b=b, topic=rng.choice(NOISE_TOPICS), amount=amount, when=when))
    for item in noise_trail.items:
        item.day, item.minute = date(2026, 1, 12) + timedelta(days=rng.randint(0, 276)), rng.randrange(7 * 60, 22 * 60)

    items = [item for trail in [*v3.trails, noise_trail] for item in trail.items]
    items.sort(key=lambda item: (item.day, item.minute))
    start = len(v2_records) + 1
    for number, item in enumerate(items, start=start):
        if item.kind == "mail":
            root = item.root.id.rsplit("/", 1)[-1] if item.root else str(number)
            item.id = f"msg:email/synthetic%40example.test/thread-{root}/{number}"
        else:
            item.id = source_ref(item.kind, number)
    records = [{"id": i.id, "kind": i.kind, "timestamp": iso(i.day, i.minute), "text": i.text} for i in items]

    shared = {subject for subject in v3.subjects if v3.subjects.count(subject) > 1}
    asked_shared = {subject for subject in shared if any(subject in ask[0] for _, _, ask in asks)}
    _invariant(asked_shared <= set(KEY_FIXES) | HARMLESS, f"every asked shared subject has a key fix: {asked_shared}")
    fixed: list[tuple[str, str, Ask]] = []
    for family, kind, (question, answer, cited, stale, form) in asks:
        fix = next((KEY_FIXES[s] for s in asked_shared if s in question and s in KEY_FIXES), None)
        if fix:
            subject = next(s for s in asked_shared if s in question)
            answer_out: str | list[str] = fix.get("answers", answer)
            stale = [*(s for s in stale if s not in fix.get("answers", [])), *fix["stale"]]
            if "cite_text" in fix:
                cited = [i for i in items if subject in i.text and fix["cite_text"] in i.text]
            fixed.append((family, kind, (question, answer_out, cited, list(dict.fromkeys(stale)), form)))  # type: ignore[arg-type]
        else:
            fixed.append((family, kind, (question, answer, cited, stale, form)))
    asks = fixed
    questions, kinds = [], []
    reworded: set[str] = set()
    for index, (family, kind, (question, answer, cited, stale, form)) in enumerate(asks, start=1):
        reword = paraphrase and kind in PARAPHRASES and kind not in reworded
        if reword:
            question = paraphrased(question, kind)
            reworded.add(kind)
        questions.append(
            {
                "id": f"q{index:02}",
                "question": question,
                "as_of": AS_OF,
                "answers": answer if isinstance(answer, list) else [answer],
                "required_citations": [c if isinstance(c, str) else c.id for c in cited],
                "stale_answers": stale,
                **({"form": form} if form else {}),
            }
        )
        kinds.append(
            {
                "id": f"q{index:02}",
                "family": FAMILIES[family],
                "kind": kind,
                **({"paraphrased": True} if reword else {}),
            }
        )
    for subject in v3.subjects:
        _invariant(subject not in v3.v2, f"{subject!r} appears in no version 2 record")
    _invariant(len(questions) == 50, f"50 questions, got {len(questions)}")
    _invariant(not paraphrase or reworded == set(PARAPHRASES), "every paraphrased kind was reworded once")
    _invariant(len({q["question"] for q in questions}) == 50, "50 different questions")
    _invariant(all(r["timestamp"] < "2026-10-19" for r in records), "every new record before the questions")
    _invariant(
        len({r["id"] for r in records} | {r["id"] for r in v2_records}) == len(records) + len(v2_records),
        "new record ids are new",
    )
    return records, questions, kinds
