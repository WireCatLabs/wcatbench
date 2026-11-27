import datetime

from sokol.unknown import UNKNOWN

DELIMITER = ";"
MAX_ROWS = 5000
INCLUDE_FULL_EMAIL = False
FILE_ENCODING = UNKNOWN
COMPRESSION = UNKNOWN
HEADER_LANGUAGE = UNKNOWN
SORT_FIELD = UNKNOWN
EXPORT_RETENTION_DAYS = UNKNOWN


def format_date(value: datetime.date) -> str:
    return value.strftime("%d.%m.%Y")


def render_row(fields: list[str]) -> str:
    return DELIMITER.join(fields)


def split_counts(total: int) -> list[int]:
    return [min(MAX_ROWS, total - start) for start in range(0, total, MAX_ROWS)]


def part_name(number: int) -> str:
    return f"part-{number}"


def mask_email(address: str) -> str:
    name, domain = address.split("@", 1)
    return f"{name[0]}***@{domain}"
