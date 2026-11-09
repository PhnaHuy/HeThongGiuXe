"""SQLAlchemy 2.x database connection, transaction, and lifecycle management."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from parking_app.infrastructure.persistence.orm_models import Base


def create_sqlite_engine(db_path: str | Path | None = None, echo: bool = False) -> Engine:
    """Create a SQLite engine configured with strict foreign keys and thread safety."""
    if db_path is None or str(db_path) == ":memory:":
        url = "sqlite:///:memory:"
    else:
        path = Path(db_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path.as_posix()}"

    if db_path is None or str(db_path) == ":memory:":
        engine = create_engine(
            url,
            echo=echo,
            connect_args={"check_same_thread": False},
            future=True,
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(
            url,
            echo=echo,
            connect_args={"check_same_thread": False},
            future=True,
        )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


class DatabaseSessionManager:
    """Thread-safe session factory and transaction manager."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )

    def init_tables(self) -> None:
        """Create all tables defined on Base."""
        Base.metadata.create_all(bind=self.engine)
        with self.engine.begin() as connection:
            columns = {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(video_sources)")
            }
            if "parking_spaces" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE video_sources ADD COLUMN parking_spaces JSON"
                )
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_parking_sessions_one_active_plate "
                "ON parking_sessions (snapshot_plate) WHERE status = 'DANG_GUI'"
            )

    def drop_tables(self) -> None:
        """Drop all tables (used primarily in test fixtures)."""
        Base.metadata.drop_all(bind=self.engine)

    @contextmanager
    def session(self) -> Generator[Session]:
        """Provide a transactional session scope with automatic commit/rollback."""
        sess: Session = self._session_factory()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()
