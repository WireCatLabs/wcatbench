"""Write the sources in the formats each contestant's own ingestion reads.

memo/ is what memo imports natively: a tg synthetic store file, a Gmail Takeout mbox, .vtt meetings, a notes folder,
an HR notes folder and documents (.md and .docx). files/ is the same archive as a user would keep it: a Telegram
Desktop export per chat (one field per line), the same mbox, the .vtt files, the notes and the documents, a .docx as
its text. `text_of` renders one source as plain text for the stores that take text records.
"""

from __future__ import annotations

import json
import os
import random
import zipfile
from collections import defaultdict
from datetime import datetime
from email.header import Header
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from wcatbench.datasets.company_round import content

ACCOUNT_ID = "1001"


def person_id(key: str) -> str:
    return str(2000 + list(content.PEOPLE).index(key))


def name(key: str) -> str:
    return content.PEOPLE[key][0]


def address(key: str) -> str:
    return content.PEOPLE[key][2]


def chat_id(chat: str) -> str:
    return str(5000 + list(content.CHATS).index(chat))


def moment(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp)


def text_of(source: dict[str, Any]) -> str:
    kind = source["kind"]
    if kind == "chat":
        title = content.CHATS[source["chat"]][0]
        head = f"{source['messages'][0][1][:10]} · чат «{title}»"
        lines = [f"{name(who)} ({at[11:16]}): {text}" for who, at, text in source["messages"]]
        return head + "\n" + "\n".join(lines)
    if kind == "mail":
        parts = []
        for sender, receivers, at, subject, body in source["messages"]:
            to = ", ".join(name(r) for r in receivers)
            parts.append(f"{at[:10]} · письмо «{subject}»\nОт: {name(sender)}. Кому: {to}\n{body}")
        return "\n\n".join(parts)
    if kind == "meeting":
        lines = [f"{name(who)}: {text}" for who, text in source["cues"]]
        return f"{source['at'][:10]} · встреча «{source['title']}»\n" + "\n".join(lines)
    return f"{source['at'][:10]} · {name(source['author'])}\n{source['body']}"


class Ids:
    """Every identifier an export shows, opaque and drawn from a seeded shuffle: a source id (s04, n00042) never
    reaches the data, so no contestant can tell a rule source from noise by its id. `index` maps each back, for
    scoring only; it stays in the dataset folder, outside every mount."""

    def __init__(self, sources: list[dict[str, Any]], seed: int) -> None:
        rng = random.Random(seed)  # noqa: S311  # nosec B311
        self.message: dict[tuple[str, int], int] = {}
        self.chat: dict[str, str] = {}
        per_chat: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
        for source in sources:
            if source["kind"] == "chat":
                self.chat[source["id"]] = chat_id(source["chat"])
                for n, (_, at, _) in enumerate(source["messages"]):
                    per_chat[source["chat"]].append((at, source["id"], n))
        for chat in sorted(per_chat):
            base = rng.randrange(1000, 90000)
            for offset, (_, sid, n) in enumerate(sorted(per_chat[chat])):
                self.message[(sid, n)] = base + offset
        self.mail: dict[tuple[str, int], tuple[int, int, str]] = {}
        for source in sources:
            if source["kind"] == "mail":
                thread = rng.randrange(10**18, 9 * 10**18)
                for n in range(len(source["messages"])):
                    self.mail[(source["id"], n)] = (
                        thread,
                        thread + n,
                        f"<{rng.getrandbits(64):016x}@severveter.example>",
                    )
        self.path: dict[str, str] = {}
        self.title: dict[str, str] = {}
        taken: set[tuple[str, str]] = set()
        for source in sources:
            if source["kind"] == "meeting":
                wanted = f"{source['at'][:10]} {source['title']}.vtt"
            elif source["kind"] in ("note", "doc"):
                wanted = source["path"]
            else:
                continue
            folder = str(source.get("folder") or source["kind"])
            stem, _, suffix = wanted.rpartition(".")
            path, copy = wanted, 2
            while (folder, path) in taken:
                path, copy = f"{stem} ({copy}).{suffix}", copy + 1
            taken.add((folder, path))
            self.path[source["id"]] = path
            if str(source.get("body", "")).startswith("# "):
                self.title[source["id"]] = source["body"].splitlines()[0][2:]

    def index(self) -> dict[str, dict[str, str]]:
        return {
            "messages": {f"{self.chat[sid]}/{mid}": sid for (sid, _), mid in self.message.items()},
            "mail": {str(gid): sid for (sid, _), (_, gid, _) in self.mail.items()}
            | {message_id: sid for (sid, _), (_, _, message_id) in self.mail.items()},
            "files": {path: sid for sid, path in self.path.items()},
            "titles": {title: sid for sid, title in self.title.items()},
        }


def person(key: str) -> dict[str, str]:
    return {"id": person_id(key), "name": name(key), "username": content.PEOPLE[key][1]}


def tg_file(sources: list[dict[str, Any]], ids: Ids) -> dict[str, Any]:
    messages = []
    for source in sources:
        if source["kind"] != "chat":
            continue
        for n, (who, at, text) in enumerate(source["messages"]):
            messages.append(
                {
                    "id": str(ids.message[(source["id"], n)]),
                    "chatId": chat_id(source["chat"]),
                    "senderId": person_id(who),
                    "senderName": name(who),
                    "timestamp": moment(at).isoformat(),
                    "text": text,
                }
            )
    return {
        "synthetic": True,
        "account": {"id": ACCOUNT_ID, "name": name(content.OWNER), "username": content.PEOPLE[content.OWNER][1]},
        "people": [person(key) for key in content.PEOPLE if key != content.OWNER and key != "natasha"],
        "chats": [
            {"id": chat_id(chat), "title": title, "kind": kind} for chat, (title, kind, _) in content.CHATS.items()
        ],
        "members": {
            chat_id(chat): [
                person(key)
                if key != content.OWNER
                else {"id": ACCOUNT_ID, "name": name(key), "username": content.PEOPLE[key][1]}
                for key in members
            ]
            for chat, (_, _, members) in content.CHATS.items()
        },
        "messages": sorted(messages, key=lambda m: m["timestamp"]),
    }


def desktop_exports(sources: list[dict[str, Any]], ids: Ids) -> dict[str, str]:
    """Telegram Desktop's JSON export, one file per chat, indented one field per line as Desktop writes it."""
    by_chat: dict[str, list[dict[str, Any]]] = {chat: [] for chat in content.CHATS}
    for source in sources:
        if source["kind"] == "chat":
            for n, (who, at, text) in enumerate(source["messages"]):
                by_chat[source["chat"]].append(
                    {
                        "id": ids.message[(source["id"], n)],
                        "type": "message",
                        "date": at[:19],
                        "from": name(who),
                        "from_id": f"user{person_id(who)}",
                        "text": text,
                    }
                )
    out = {}
    for chat, messages in by_chat.items():
        title, kind, _ = content.CHATS[chat]
        export = {
            "name": title,
            "type": "private_group" if kind == "group" else "personal_chat",
            "id": int(chat_id(chat)),
            "messages": sorted(messages, key=lambda m: (m["date"], m["id"])),
        }
        out[f"chats/{title}/result.json"] = json.dumps(export, ensure_ascii=False, indent=1)
    return out


def mbox(sources: list[dict[str, Any]], ids: Ids) -> str:
    blocks = []
    for source in sources:
        if source["kind"] != "mail":
            continue
        first = None
        for n, (sender, receivers, at, subject, body) in enumerate(source["messages"]):
            thread, gid, message_id = ids.mail[(source["id"], n)]
            when = moment(at)
            headers = [
                f"From {gid}@xxx {when.strftime('%a %b %d %H:%M:%S %z %Y')}",
                f"X-GM-THRID: {thread}",
                "X-Gmail-Labels: Inbox",
                f"Message-ID: {message_id}",
                f"From: {Header(name(sender), 'utf-8').encode()} <{address(sender)}>",
                "To: " + ", ".join(f"{Header(name(r), 'utf-8').encode()} <{address(r)}>" for r in receivers),
                f"Subject: {Header(subject, 'utf-8').encode()}",
                f"Date: {format_datetime(when)}",
                "MIME-Version: 1.0",
                "Content-Type: text/plain; charset=UTF-8",
                "Content-Transfer-Encoding: 8bit",
            ]
            if first:
                headers += [f"In-Reply-To: {first}", f"References: {first}"]
            first = first or message_id
            escaped = "\n".join(">" + line if line.startswith("From ") else line for line in body.splitlines())
            blocks.append("\n".join(headers) + "\n\n" + escaped + "\n")
    return "\n".join(blocks)


def vtt(source: dict[str, Any]) -> str:
    cues = ["WEBVTT", ""]
    for n, (who, text) in enumerate(source["cues"]):
        start, end = n * 8, n * 8 + 7
        cues += [
            f"00:{start // 60:02d}:{start % 60:02d}.000 --> 00:{end // 60:02d}:{end % 60:02d}.000",
            f"<v {name(who)}>{text}",
            "",
        ]
    return "\n".join(cues)


def docx(text: str) -> bytes:
    """A minimal Word document: one paragraph per line, the parts Word and memo's reader need."""
    paragraphs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>' for line in text.splitlines()
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def touch(path: Path, stamp: str) -> None:
    """A file's modification time is its date, as on the owner's disk: notes and documents carry no other."""
    seconds = moment(stamp).timestamp()
    os.utime(path, (seconds, seconds))


def write(out: Path, sources: list[dict[str, Any]], seed: int) -> dict[str, int]:
    """Both layouts under `out`, and ids.json beside them. Returns the count of sources per kind."""
    ids = Ids(sources, seed)
    (out / "ids.json").parent.mkdir(parents=True, exist_ok=True)
    memo, files = out / "memo", out / "files"
    for folder in (memo / "notes", memo / "hr", memo / "docs", memo / "meetings", files):
        folder.mkdir(parents=True, exist_ok=True)
    (memo / "chats.json").write_text(json.dumps(tg_file(sources, ids), ensure_ascii=False))
    box = mbox(sources, ids)
    (memo / "mail.mbox").write_text(box)
    (files / "mail").mkdir(exist_ok=True)
    (files / "mail" / "mail.mbox").write_text(box)
    for relative, text in desktop_exports(sources, ids).items():
        (files / relative).parent.mkdir(parents=True, exist_ok=True)
        (files / relative).write_text(text)
    counts: dict[str, int] = {}
    for source in sources:
        kind = source["kind"]
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "meeting":
            for root in (memo / "meetings", files / "meetings"):
                root.mkdir(parents=True, exist_ok=True)
                (root / ids.path[source["id"]]).write_text(vtt(source))
                touch(root / ids.path[source["id"]], source["at"])
        elif kind == "note":
            for root in (memo / source["folder"], files / source["folder"]):
                (root / ids.path[source["id"]]).parent.mkdir(parents=True, exist_ok=True)
                (root / ids.path[source["id"]]).write_text(source["body"] + "\n")
                touch(root / ids.path[source["id"]], source["at"])
        elif kind == "doc":
            path = ids.path[source["id"]]
            (files / "docs").mkdir(exist_ok=True)
            if path.endswith(".docx"):
                (memo / "docs" / path).write_bytes(docx(source["body"]))
                (files / "docs" / path.replace(".docx", ".txt")).write_text(source["body"] + "\n")
            else:
                (memo / "docs" / path).write_text(source["body"] + "\n")
                (files / "docs" / path).write_text(source["body"] + "\n")
            for written in (memo / "docs" / path, files / "docs" / path.replace(".docx", ".txt")):
                touch(written, source["at"])
    (out / "ids.json").write_text(json.dumps(ids.index(), ensure_ascii=False))
    return counts
