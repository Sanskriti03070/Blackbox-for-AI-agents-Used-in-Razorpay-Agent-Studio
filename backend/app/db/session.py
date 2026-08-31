from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
import app.simulation.models  # noqa: F401 - register domain models with Base.metadata

engine = create_engine(str(get_settings().database_url), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db_session() -> Generator[Session, None, None]:
    """Provide one SQLAlchemy session per request and always close it."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
