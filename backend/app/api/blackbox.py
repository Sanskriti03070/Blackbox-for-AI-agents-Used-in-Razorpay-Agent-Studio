from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.investigation import build_investigation
from app.agents.repository import get_agent_run, get_agent_trace, list_agent_runs
from app.db.session import get_db_session


SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "card_number",
    "card",
    "cvv",
    "secret",
    "password",
    "token",
}


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _sanitize_dict(value)

    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]

    return value


def _sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}

    for key, value in data.items():
        lower_key = key.lower()

        if any(sensitive_key in lower_key for sensitive_key in SENSITIVE_KEYS):
            output[key] = "<REDACTED>"
        else:
            output[key] = _sanitize_value(value)

    return output


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


class AgentRunSummaryOut(BaseModel):
    run_id: UUID
    agent_name: str
    agent_version: str
    payment_id: UUID | None
    status: str
    selected_action: str | None
    confidence: float | None
    outcome: str | None
    user_request: str
    started_at: str
    completed_at: str | None


class InvestigationOut(BaseModel):
    run: dict[str, Any]
    incident: dict[str, Any]
    timeline: dict[str, Any]
    conclusion: str
    evidence_integrity: dict[str, Any]
    evidence: list[dict[str, Any]]


router = APIRouter()


@router.get(
    "/black-box/runs",
    response_model=List[AgentRunSummaryOut],
)
def list_runs(
    db: Session = Depends(get_db_session),
):
    runs = list_agent_runs(db)

    return [
        AgentRunSummaryOut(
            run_id=run.run_id,
            agent_name=run.agent_name,
            agent_version=run.agent_version,
            payment_id=run.payment_id,
            status=run.status,
            selected_action=run.selected_action,
            confidence=run.confidence,
            outcome=run.outcome,
            user_request=run.user_request,
            started_at=run.started_at.isoformat(),
            completed_at=(
                run.completed_at.isoformat()
                if run.completed_at
                else None
            ),
        )
        for run in runs
    ]


@router.get(
    "/black-box/runs/{run_id}",
    response_model=AgentRunOut,
)
def get_run(
    run_id: UUID,
    db: Session = Depends(get_db_session),
):
    run = get_agent_run(db, run_id)

    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Agent run not found",
        )

    events = get_agent_trace(db, run.run_id)

    sanitized_events = []

    for event in events:
        payload = None
        result = None

        if event.payload is not None:
            try:
                payload = _sanitize_dict(event.payload)
            except Exception:
                payload = None

        if event.result is not None:
            try:
                result = _sanitize_dict(event.result)
            except Exception:
                result = None

        sanitized_events.append(
            AgentTraceEventOut(
                id=event.id,
                sequence=event.sequence,
                timestamp=event.timestamp.isoformat(),
                source=event.source,
                event_type=event.event_type,
                duration_ms=event.duration_ms,
                payload=payload,
                result=result,
                error_text=event.error_text,
            )
        )

    return AgentRunOut(
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
        completed_at=(
            run.completed_at.isoformat()
            if run.completed_at
            else None
        ),
        error_summary=run.error_summary,
        events=sanitized_events,
    )


@router.get(
    "/black-box/investigations/{run_id}",
    response_model=InvestigationOut,
)
def get_investigation(
    run_id: UUID,
    db: Session = Depends(get_db_session),
):
    run = get_agent_run(db, run_id)

    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Agent run not found",
        )

    events = get_agent_trace(db, run.run_id)

    investigation = build_investigation(
        run,
        events,
    )

    return _sanitize_dict(investigation)
