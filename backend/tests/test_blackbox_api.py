import json
import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.agents.repository import create_agent_run, append_trace_event, get_agent_trace
from app.agents.models import AgentRunStatus
from app.db.session import get_db_session


def _override_db_with_session(session):
    # helper to return a dependency override that uses the test session's bind
    from sqlalchemy.orm import sessionmaker

    def _get_test_db():
        TestSession = sessionmaker(bind=session.get_bind())
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    return _get_test_db


def test_get_run_returns_run_and_timeline(session):
    # create a run and events
    run = create_agent_run(
        session,
        agent_name="subscription_recovery",
        agent_version="0.1.0",
        user_request="Inspect this run",
    )
    append_trace_event(session, run.run_id, sequence=1, source="agent", event_type="agent_started", payload={"foo": "bar"})
    append_trace_event(session, run.run_id, sequence=2, source="agent", event_type="context_loaded", payload={"payment_id": str(uuid.uuid4())})
    session.commit()

    # Override DB dependency so the TestClient uses the test session's connection
    app.dependency_overrides[get_db_session] = _override_db_with_session(session)
    client = TestClient(app)
    resp = client.get(f"/api/v1/black-box/runs/{run.run_id}")
    app.dependency_overrides.pop(get_db_session, None)
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == str(run.run_id)
    assert data["agent_name"] == "subscription_recovery"
    assert isinstance(data["events"], list)
    assert [e["sequence"] for e in data["events"]] == [1, 2]


def test_get_run_missing_returns_404(session):
    client = TestClient(app)
    resp = client.get(f"/api/v1/black-box/runs/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_get_run_malformed_uuid_returns_422():
    client = TestClient(app)
    resp = client.get("/api/v1/black-box/runs/not-a-uuid")
    assert resp.status_code == 422


def test_sensitive_fields_are_redacted(session):
    run = create_agent_run(session, agent_name="subscription_recovery", agent_version="0.1.0", user_request="Inspect secrets")
    append_trace_event(session, run.run_id, sequence=1, source="agent", event_type="agent_started", payload={"api_key": "SECRET"})
    append_trace_event(session, run.run_id, sequence=2, source="agent", event_type="decision_generated", result={"decision": "retry", "authorization": "******"})
    session.commit()

    # Override DB dependency so the TestClient uses the test session's connection
    app.dependency_overrides[get_db_session] = _override_db_with_session(session)
    client = TestClient(app)
    resp = client.get(f"/api/v1/black-box/runs/{run.run_id}")
    app.dependency_overrides.pop(get_db_session, None)
    assert resp.status_code == 200
    data = resp.json()
    serialized = json.dumps([{"payload": e.get("payload"), "result": e.get("result") } for e in data["events"]])
    assert "SECRET" not in serialized
    assert "******" not in serialized
