"""Danil Pismenny's Memory Bank (github.com/dapi/memory-bank) installed into a task workspace as its README says.

`template/memory-bank/` becomes `memory-bank/`, `template/init.sh` becomes `./init.sh`, and the root `AGENTS.md` gets
the routing block that memory-bank-cli writes (docs/agent-instructions.md). The template stays byte for byte as
pinned. The rules-trial sources, when given, go where his brownfield protocol (docs/brownfield-adaptation-protocol.md,
steps 2 and 6) puts existing project sources: a decision becomes a historical ADR, accepted, with no `supersedes`
(raw ingest, as every store got the raw records); a chat, note or meeting is not a decision record (adr/README.md),
so it stays as evidence in the intake document outside `memory-bank/`.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
from pathlib import Path

from wcatbench.core.types import Record

COMMIT = "e1b428dd7aed66eda99b3cbc6073c29f7da921de"
TEMPLATE = Path(os.environ.get("WCATBENCH_MEMORY_BANK", "/home/leemour/.cache/wcat-dapi-mb/src")) / "template"

# Byte for byte as docs/agent-instructions.md shows it for memory-bank-cli v1.0.0.
MANAGED_BLOCK = (
    "<!-- MEMORY BANK START -->\n"
    "<!-- MEMORY BANK MANAGED BLOCK VERSION: 1 -->\n"
    "Before substantial delivery work, read memory-bank/README.md, memory-bank/dna/README.md, "
    "and memory-bank/flows/routing.md.\n"
    "Keep project-specific instructions outside this managed block; "
    "they take precedence outside this routing contract.\n"
    "<!-- MEMORY BANK END -->\n"
)

SLUG = {"Сокол": "sokol", "Сокол-Лайт": "sokol-lite", "Сапсан": "sapsan", "Компания": "company"}

ADR = """---
title: "{title}"
doc_kind: adr
doc_function: canonical
purpose: "Фиксирует архитектурное или инженерное решение, его текущий `decision_status` и последствия."
derived_from: []
status: active
decision_status: accepted
date: {date}
decision_makers:
  - {author}
consulted: []
informed: []
audience: humans_and_agents
must_not_define:
  - current_system_state
  - implementation_plan
---

# {title}

## Контекст

Проект: {project}. Запись от {date}, автор: {author}.

## Решение

{body}
"""


INTAKE = """# Brownfield intake PRD

Временный evidence-документ вне Memory Bank: существующие источники проекта, которые не являются decision records.
Каждая запись хранит источник, дату и автора; это не asserted facts.

## Source inventory

{entries}
"""

INTAKE_ENTRY = """### {kind} · {date} · {author}

Проект: {project}. Тип источника: {kind}.

{body}
"""


def project_of(record: Record) -> str:
    return record.metadata.get("project") or record.source or ""


def body_of(record: Record) -> str:
    return record.text.split("\n", 1)[1] if "\n" in record.text else record.text


def adr(number: int, record: Record) -> tuple[str, str]:
    """One source as an ADR: only what the source says, no option table or consequences made up for it."""
    body = body_of(record)
    words = body.split()
    title = f"ADR-{number:03d}: " + " ".join(words[:8]).rstrip(",.:;—") + ("…" if len(words) > 8 else "")
    project = project_of(record)
    text = ADR.format(
        title=title.replace('"', "'"),
        date=record.timestamp[:10],
        author=record.author or "",
        project=project,
        body=body,
    )
    return f"ADR-{number:03d}-{SLUG.get(project, 'project')}.md", text


def layout(records: list[Record]) -> dict[str, str]:
    """The files the sources become, by path relative to the workspace root."""
    ordered = sorted(records, key=lambda record: (record.timestamp, record.id))
    files = dict(adr(number, record) for number, record in enumerate((r for r in ordered if r.kind == "decision"), 1))
    files = {f"memory-bank/adr/{name}": text for name, text in files.items()}
    entries = [
        INTAKE_ENTRY.format(
            kind=record.kind,
            date=record.timestamp[:10],
            author=record.author or "",
            project=project_of(record),
            body=body_of(record),
        )
        for record in ordered
        if record.kind != "decision"
    ]
    if entries:
        files["brownfield-intake-prd.md"] = INTAKE.format(entries="\n".join(entries))
    return files


def whole_text(records: list[Record]) -> str:
    """The written layout as one text, for the whole-files control: the template itself is left out."""
    return "\n\n".join(f"<!-- {path} -->\n{text}" for path, text in sorted(layout(records).items()))


def pinned(template: Path) -> None:
    clone = template.parent
    if not (clone / ".git").exists():
        return
    head = subprocess.run(  # noqa: S603  # nosec B603 B607
        ["git", "-C", str(clone), "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if head != COMMIT:
        raise RuntimeError(f"memory-bank clone is at {head}, the trial pins {COMMIT}")


def install(into: Path, records: list[Record] | None = None, template: Path | None = None) -> int:
    """Install the bank into `into` (the workspace root); returns the number of files written from the sources."""
    source = template or TEMPLATE
    pinned(source)
    shutil.copytree(source / "memory-bank", into / "memory-bank")
    shutil.copy2(source / "init.sh", into / "init.sh")
    agents = into / "AGENTS.md"
    existing = agents.read_text() if agents.exists() else ""
    agents.write_text(f"{existing.rstrip()}\n\n{MANAGED_BLOCK}" if existing.strip() else MANAGED_BLOCK)
    files = layout(records or [])
    for path, text in files.items():
        (into / path).write_text(text)
    return len(files)
