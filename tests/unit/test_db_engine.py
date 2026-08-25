from sqlalchemy import create_engine, event, text

from app.db.engine import (
    configure_sqlite_connection,
    sqlite_connect_args,
)


def test_file_sqlite_engine_uses_wal_and_busy_timeout(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrency.db'}",
        connect_args=sqlite_connect_args(),
    )
    event.listen(engine, "connect", configure_sqlite_connection)

    with engine.connect() as connection:
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        busy_timeout = connection.execute(text("PRAGMA busy_timeout")).scalar_one()

    engine.dispose()

    assert journal_mode.lower() == "wal"
    assert busy_timeout == 30_000
