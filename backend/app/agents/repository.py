import enum
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.models import AgentRun, AgentRunStatus, AgentTraceEvent


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]

    return value


def create_agent_run(
    session: Session,
    *,
    agent_name: str,
    agent_version: str,
    user_request: str,
    run_id: uuid.UUID | None = None,
    merchant_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    subscription_id: uuid.UUID | None = None,
    payment_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
    status: str = AgentRunStatus.STARTED.value,
) -> AgentRun:
    agent_run = AgentRun(
        run_id=run_id or uuid.uuid4(),
        agent_name=agent_name,
        agent_version=agent_version,
        merchant_id=merchant_id,
        customer_id=customer_id,
        subscription_id=subscription_id,
        payment_id=payment_id,
        user_request=user_request,
        status=status,
        metadata_=_json_safe(metadata) if metadata is not None else None,
    )
    session.add(agent_run)
    session.flush()
    return agent_run


def get_agent_run(session: Session, run_id: uuid.UUID) -> AgentRun | None:
    stmt = select(AgentRun).options(selectinload(AgentRun.events)).where(AgentRun.run_id == run_id)
    return session.scalar(stmt)


def list_agent_runs(session: Session, *, limit: int = 50) -> list[AgentRun]:
    stmt = select(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def update_agent_run_context(
    session: Session,
    run_id: uuid.UUID,
    *,
    merchant_id: uuid.UUID | None = None,
    customer_id: uuid.UUID | None = None,
    subscription_id: uuid.UUID | None = None,
) -> AgentRun:
    agent_run = get_agent_run(session, run_id)
    if agent_run is None:
        raise ValueError(f"Agent run {run_id} not found")

    if merchant_id is not None:
        agent_run.merchant_id = merchant_id
    if customer_id is not None:
        agent_run.customer_id = customer_id
    if subscription_id is not None:
        agent_run.subscription_id = subscription_id
    session.flush()
    return agent_run


def complete_agent_run(
    session: Session,
    run_id: uuid.UUID,
    *,
    selected_action: str | None = None,
    confidence: float | None = None,
    outcome: str | None = None,
    completed_at: datetime | None = None,
) -> AgentRun:
    agent_run = get_agent_run(session, run_id)
    if agent_run is None:
        raise ValueError(f"Agent run {run_id} not found")

    agent_run.status = AgentRunStatus.COMPLETED.value
    if selected_action is not None:
        agent_run.selected_action = selected_action
    if confidence is not None:
        agent_run.confidence = float(confidence)
    if outcome is not None:
        agent_run.outcome = outcome
    agent_run.completed_at = completed_at or datetime.now(timezone.utc)
    session.flush()
    return agent_run


def fail_agent_run(
    session: Session,
    run_id: uuid.UUID,
    *,
    error_summary: str,
    outcome: str | None = None,
    completed_at: datetime | None = None,
) -> AgentRun:
    agent_run = get_agent_run(session, run_id)
    if agent_run is None:
        raise ValueError(f"Agent run {run_id} not found")

    agent_run.status = AgentRunStatus.FAILED.value
    agent_run.error_summary = error_summary
    if outcome is not None:
        agent_run.outcome = outcome
    agent_run.completed_at = completed_at or datetime.now(timezone.utc)
    session.flush()
    return agent_run


def append_trace_event(
    session: Session,
    run_id: uuid.UUID,
    *,
    sequence: int,
    source: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    duration_ms: int | None = None,
    error_text: str | None = None,
    timestamp: datetime | None = None,
) -> AgentTraceEvent:
    if session.get(AgentRun, run_id) is None:
        raise ValueError(f"Agent run {run_id} not found")

    event = AgentTraceEvent(
        run_id=run_id,
        sequence=sequence,
        timestamp=timestamp or datetime.now(timezone.utc),
        source=source,
        event_type=event_type,
        duration_ms=duration_ms,
        payload=_json_safe(payload) if payload is not None else None,
        result=_json_safe(result) if result is not None else None,
        error_text=error_text,
    )
    session.add(event)
    session.flush()
    return event


def get_agent_trace(session: Session, run_id: uuid.UUID, *, limit: int | None = None) -> list[AgentTraceEvent]:
    stmt = select(AgentTraceEvent).where(AgentTraceEvent.run_id == run_id).order_by(AgentTraceEvent.sequence)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())
