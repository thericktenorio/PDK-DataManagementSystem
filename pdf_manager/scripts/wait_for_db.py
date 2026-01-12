import os
import sys
import time

import psycopg
from psycopg import OperationalError


def env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


# If we are using SQLite, do not block startup waiting for Postgres.
if env_bool("USE_SQLITE", default=True):
    sys.exit(0)


host = os.getenv("POSTGRES_HOST", "pdf_db")
port = int(os.getenv("POSTGRES_PORT", "5432"))
user = os.getenv("POSTGRES_USER", "pdfmgr")
password = os.getenv("POSTGRES_PASSWORD", "pdfmgrpw")
dbname = os.getenv("POSTGRES_DB", "pdfmgr")


# Try for up to 60 seconds
for _ in range(60):
    try:
        # psycopg 3 uses psycopg.connect(...)
        with psycopg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            dbname=dbname,
            connect_timeout=3,
        ) as _conn:
            sys.exit(0)
    except OperationalError:
        time.sleep(1)

print("Database not available after 60 seconds.", file=sys.stderr)
sys.exit(1)
