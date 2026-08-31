import app.agents.subscription_recovery.agent as subscription_recovery_agent_module
import os
from collections.abc import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, sessionmaker
import pytest
from app.db.base import Base
import app.agents.models  # noqa: F401
import app.simulation.models  # noqa: F401

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://razorpay:change-me-for-local-development@postgres:5432/razorpay_black_box_test")

@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    url = TEST_URL
    admin_url = url.rsplit("/", 1)[0] + "/postgres"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.scalar(text("SELECT 1 FROM pg_database WHERE datname = 'razorpay_black_box_test'"))
        if not exists: connection.execute(text("CREATE DATABASE razorpay_black_box_test"))
    admin.dispose()
    test_engine = create_engine(url)
    Base.metadata.drop_all(test_engine); Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine); test_engine.dispose()

@pytest.fixture
def session(engine: Engine) -> Generator[Session, None, None]:
    connection: Connection = engine.connect(); transaction = connection.begin()
    test_session = sessionmaker(bind=connection, expire_on_commit=False)()
    yield test_session
    test_session.close(); transaction.rollback(); connection.close()


@pytest.fixture(autouse=True)
def patch_agent_session_local(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure agent-managed sessions (SessionLocal()) share the test transaction."""
    bind = session.get_bind()
    test_sessionmaker = sessionmaker(bind=bind, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(subscription_recovery_agent_module, "SessionLocal", test_sessionmaker)
