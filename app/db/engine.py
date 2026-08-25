"""SQLite engine configuration."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url

from app.core.config import settings


SQLITE_BUSY_TIMEOUT_MILLISECONDS = 30_000


def sqlite_connect_args() -> dict:
    return {
        "check_same_thread": False,
        "timeout": SQLITE_BUSY_TIMEOUT_MILLISECONDS / 1000,
    }


def configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute(
            f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MILLISECONDS}"
        )
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


database_url = make_url(settings.database_url)
is_sqlite = database_url.get_backend_name() == "sqlite"
engine = create_engine(
    settings.database_url,
    connect_args=sqlite_connect_args() if is_sqlite else {},
)
if is_sqlite:
    event.listen(engine, "connect", configure_sqlite_connection)
