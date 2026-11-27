from sokol.unknown import UNKNOWN

RETENTION_DAYS = 90
ARCHIVE_FORMAT = "parquet"
REPORT_TIMEZONE = "Europe/Moscow"
MAX_REPORT_MB = 50
COMPRESSION = UNKNOWN
ENCRYPTION = UNKNOWN
OWNER_EMAIL = UNKNOWN

CLEANUP_HOUR = 3


def retention_days(department):
    return 90
