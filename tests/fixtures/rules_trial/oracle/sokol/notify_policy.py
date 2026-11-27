import datetime
from zoneinfo import ZoneInfo

from sokol.unknown import UNKNOWN

QUIET_START = "22:00"
QUIET_END = "08:00"
QUIET_TIMEZONE = "Europe/Moscow"
WEBHOOK_TIMEOUT_SECONDS = 7
WEBHOOK_MAX_ATTEMPTS = 4
MAX_PER_DAY = UNKNOWN
CHANNEL = UNKNOWN
SENDER_NAME = UNKNOWN
ESCALATION_MINUTES = UNKNOWN
BATCH_SIZE = UNKNOWN


def in_quiet_hours(moment: datetime.datetime) -> bool:
    local = moment.astimezone(ZoneInfo(QUIET_TIMEZONE)).time()
    return local >= datetime.time(22, 0) or local < datetime.time(8, 0)


def webhook_host_allowed(host: str) -> bool:
    return host == "api.sokol-pay.example"
