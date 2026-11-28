"""Write the sources in the formats each contestant's own ingestion reads.

memo/ is what memo imports natively: a tg synthetic store file, a Gmail Takeout mbox, .vtt meetings, a notes folder,
an HR notes folder and documents (.md and .docx). files/ is the same archive as a user would keep it: a Telegram
Desktop export per chat (one field per line), the same mbox, the .vtt files, the notes and the documents, a .docx as
its text. `text_of` renders one source as plain text for the stores that take text records.
"""

from __future__ import annotations

import json
import os
import zipfile
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


def person(key: str) -> dict[str, str]:
    return {"id": person_id(key), "name": name(key), "username": content.PEOPLE[key][1]}


def tg_file(sources: list[dict[str, Any]]) -> dict[str, Any]:
    messages = []
    for source in sources:
        if source["kind"] != "chat":
            continue
        for n, (who, at, text) in enumerate(source["messages"]):
            messages.append(
                {
                    "id": f"{source['id']}-{n}",
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


def desktop_exports(sources: list[dict[str, Any]]) -> dict[str, str]:
    """Telegram Desktop's JSON export, one file per chat, indented one field per line as Desktop writes it."""
    by_chat: dict[str, list[dict[str, Any]]] = {chat: [] for chat in content.CHATS}
    for source in sources:
        if source["kind"] == "chat":
            for n, (who, at, text) in enumerate(source["messages"]):
                by_chat[source["chat"]].append(
                    {
                        "id": int(source["id"][1:]) * 10 + n,
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
            "messages": sorted(messages, key=lambda m: m["date"]),
        }
        out[f"chats/{title}/result.json"] = json.dumps(export, ensure_ascii=False, indent=1)
    return out


def mbox(sources: list[dict[str, Any]]) -> str:
    blocks = []
    serial = 0
    for source in sources:
        if source["kind"] != "mail":
            continue
        thread = 1790000000000000000 + int(source["id"][1:]) * 100
        first = None
        for sender, receivers, at, subject, body in source["messages"]:
            serial += 1
            gid = thread + serial % 100
            message_id = f"<{source['id']}.{serial}@severveter.example>"
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


def meeting_name(source: dict[str, Any]) -> str:
    return f"{source['at'][:10]} {source['title']} {source['id']}.vtt"


def write(out: Path, sources: list[dict[str, Any]]) -> dict[str, int]:
    """Both layouts under `out`. Returns the count of files per kind."""
    memo, files = out / "memo", out / "files"
    for folder in (memo / "notes", memo / "hr", memo / "docs", memo / "meetings", files):
        folder.mkdir(parents=True, exist_ok=True)
    (memo / "chats.json").write_text(json.dumps(tg_file(sources), ensure_ascii=False))
    box = mbox(sources)
    (memo / "mail.mbox").write_text(box)
    (files / "mail").mkdir(exist_ok=True)
    (files / "mail" / "mail.mbox").write_text(box)
    for relative, text in desktop_exports(sources).items():
        (files / relative).parent.mkdir(parents=True, exist_ok=True)
        (files / relative).write_text(text)
    counts: dict[str, int] = {}
    for source in sources:
        kind = source["kind"]
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "meeting":
            for root in (memo / "meetings", files / "meetings"):
                root.mkdir(parents=True, exist_ok=True)
                (root / meeting_name(source)).write_text(vtt(source))
                touch(root / meeting_name(source), source["at"])
        elif kind == "note":
            for root in (memo / source["folder"], files / source["folder"]):
                (root / source["path"]).parent.mkdir(parents=True, exist_ok=True)
                (root / source["path"]).write_text(source["body"] + "\n")
                touch(root / source["path"], source["at"])
        elif kind == "doc":
            path = source["path"]
            (files / "docs").mkdir(exist_ok=True)
            if path.endswith(".docx"):
                (memo / "docs" / path).write_bytes(docx(source["body"]))
                (files / "docs" / path.replace(".docx", ".txt")).write_text(source["body"] + "\n")
            else:
                (memo / "docs" / path).write_text(source["body"] + "\n")
                (files / "docs" / path).write_text(source["body"] + "\n")
            for written in (memo / "docs" / path, files / "docs" / path.replace(".docx", ".txt")):
                touch(written, source["at"])
    return counts
