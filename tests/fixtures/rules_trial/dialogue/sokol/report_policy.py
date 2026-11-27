from sokol.unknown import UNKNOWN

RETENTION_DAYS = 90
ARCHIVE_FORMAT = "parquet"
REPORT_TIMEZONE = "Europe/Moscow"
MAX_REPORT_MB = 50
COMPRESSION = UNKNOWN
ENCRYPTION = UNKNOWN
OWNER_EMAIL = UNKNOWN


def retention_days(department):
    return 365 if department == "audit" else 90
