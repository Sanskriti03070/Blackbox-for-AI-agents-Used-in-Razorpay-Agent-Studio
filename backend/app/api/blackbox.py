from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.repository import get_agent_run, get_agent_trace
from app.db.session import get_db_session, SessionLocal


SENSITIVE_KEYS = {"api_key", "authorization", "card_number", "card", "cvv", "secret", "password", "token"}


def _sanitize_value(v: Any) -> Any:
    if isinstance(v, dict):
        return _sanitize_dict(v)
    if isinstance(v, list):
        return [_sanitize_value(x) for x in v]
    return v


def _sanitize_dict(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        low = k.lower()
        if any(sk in low for sk in SENSITIVE_KEYS):
            out[k] = "<REDACTED>"
        else:
            out[k] = _sanitize_value(v)
    return out


class AgentTraceEventOut(BaseModel):
    id: UUID
    sequence: int
    timestamp: str
    source: str
    event_type: str
    duration_ms: int | None
    payload: dict | None
    result: dict | None
    error_text: str | None


class AgentRunOut(BaseModel):
    run_id: UUID
    agent_name: str
    agent_version: str
    merchant_id: UUID | None
    customer_id: UUID | None
    subscription_id: UUID | None
    payment_id: UUID | None
    user_request: str
    status: str
    selected_action: str | None
    confidence: float | None
    outcome: str | None
    started_at: str
    completed_at: str | None
    error_summary: str | None
    events: List[AgentTraceEventOut]


router = APIRouter()


@router.get("/black-box/runs/{run_id}", response_model=AgentRunOut)
def get_run(run_id: UUID, db: Session = Depends(get_db_session)):
    # Read through a short-lived local session to ensure visibility of committed runs
    local_db = SessionLocal()
    try:
        run = get_agent_run(local_db, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Agent run not found")
        events = get_agent_trace(local_db, run.run_id)
        # sanitize payloads and results
        sanitized_events = []
        for ev in events:
            payload = None
            result = None
            if ev.payload is not None:
                try:
                    payload = _sanitize_dict(ev.payload)
                except Exception:
                    payload = None
            if ev.result is not None:
                try:
                    result = _sanitize_dict(ev.result)
                except Exception:
                    result = None
            sanitized_events.append(
                AgentTraceEventOut(
                    id=ev.id,
                    sequence=ev.sequence,
                    timestamp=ev.timestamp.isoformat(),
                    source=ev.source,
                    event_type=ev.event_type,
                    duration_ms=ev.duration_ms,
                    payload=payload,
                    result=result,
                    error_text=ev.error_text,
                )
            )
        out = AgentRunOut(
            run_id=run.run_id,
            agent_name=run.agent_name,
            agent_version=run.agent_version,
            merchant_id=run.merchant_id,
            customer_id=run.customer_id,
            subscription_id=run.subscription_id,
            payment_id=run.payment_id,
            user_request=run.user_request,
            status=run.status,
            selected_action=run.selected_action,
            confidence=run.confidence,
            outcome=run.outcome,
            started_at=run.started_at.isoformat(),
            completed_at=run.completed_at.isoformat() if run.completed_at else None,
            error_summary=run.error_summary,
            events=sanitized_events,
        )
        return out
    finally:
        local_db.close()
