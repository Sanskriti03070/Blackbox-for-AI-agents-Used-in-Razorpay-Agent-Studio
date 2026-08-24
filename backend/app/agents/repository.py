import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.models import AgentRun, AgentRunStatus, AgentTraceEvent


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
        metadata_=metadata,
    )
    session.add(agent_run)
    session.flush()
    return agent_run


def get_agent_run(session: Session, run_id: uuid.UUID) -> AgentRun | None:
    stmt = select(AgentRun).options(selectinload(AgentRun.events)).where(AgentRun.run_id == run_id)
    return session.scalar(stmt)


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
        payload=payload,
        result=result,
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
