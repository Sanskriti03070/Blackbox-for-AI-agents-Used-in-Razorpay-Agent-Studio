import time
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.agents.repository import (
    AgentRun,
    append_trace_event,
    complete_agent_run,
    create_agent_run,
    fail_agent_run,
    get_agent_run,
    update_agent_run_context,
)
from app.agents.subscription_recovery.context import (
    SubscriptionRecoveryContextNotFoundError,
    load_subscription_recovery_context,
)
from app.agents.subscription_recovery.graph import build_subscription_recovery_graph
from app.agents.subscription_recovery.decision import DecisionModel
from app.agents.subscription_recovery.executor import ActionExecutor
from app.agents.subscription_recovery.model import OpenAIDecisionModel
from app.agents.subscription_recovery.state import SubscriptionRecoveryState
from app.core.config import get_settings
from app.db.session import SessionLocal

AGENT_NAME = "subscription_recovery"
AGENT_VERSION = get_settings().app_version


@dataclass(frozen=True, slots=True)
class SubscriptionRecoveryRequest:
    """Input accepted by the agent before real context and tools are added."""

    user_request: str
    run_id: uuid.UUID | None = None
    merchant_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    payment_id: uuid.UUID | None = None


class SubscriptionRecoveryAgent:
    """LLM-backed agent with deterministic, allowlisted action execution."""

    def __init__(self, session: Session | None = None, model: DecisionModel | None = None) -> None:
        self.graph = build_subscription_recovery_graph()
        self._session = session
        self._model = model

    def _run_payload(self, state: SubscriptionRecoveryState) -> dict[str, Any]:
        return {
            "merchant_id": state.get("merchant_id"),
            "customer_id": state.get("customer_id"),
            "subscription_id": state.get("subscription_id"),
            "payment_id": state.get("payment_id"),
            "user_request": state.get("user_request"),
        }

    def _record_event(
        self,
        session: Session,
        run_id: uuid.UUID,
        sequence: int,
        event_type: str,
        *,
        source: str = AGENT_NAME,
        payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        error_text: str | None = None,
    ) -> None:
        try:
            append_trace_event(
                session,
                run_id,
                sequence=sequence,
                source=source,
                event_type=event_type,
                payload=payload,
                result=result,
                duration_ms=duration_ms,
                error_text=error_text,
            )
        except Exception:
            session.rollback()

    async def run(self, request: SubscriptionRecoveryRequest) -> SubscriptionRecoveryState:
        state: SubscriptionRecoveryState = {
            "user_request": request.user_request,
            "messages": [],
            "errors": [],
        }
        run_id = request.run_id or uuid.uuid4()
        state["run_id"] = run_id
        for field in ("merchant_id", "customer_id", "subscription_id", "payment_id"):
            value = getattr(request, field)
            if value is not None:
                state[field] = value  # type: ignore[literal-required]

        if request.payment_id is None:
            if self._session is not None:
                self._create_agent_run(self._session, state)
                result = await self.graph.ainvoke(state)
                self._persist_missing_context(self._session, state, result)
                return result

            with SessionLocal() as session:
                self._create_agent_run(session, state)
                session.commit()
                result = await self.graph.ainvoke(state)
                self._persist_missing_context(session, state, result)
                session.commit()
                return result

        if self._session is not None:
            self._create_agent_run(self._session, state)
            return await self._run_with_session(state, self._session)

        with SessionLocal() as session:
            self._create_agent_run(session, state)
            session.commit()
            result = await self._run_with_session(state, session)
            session.commit()
            return result

    def _create_agent_run(self, session: Session, state: SubscriptionRecoveryState) -> AgentRun | None:
        try:
            agent_run = create_agent_run(
                session,
                agent_name=AGENT_NAME,
                agent_version=AGENT_VERSION,
                user_request=state["user_request"],
                run_id=state["run_id"],
                merchant_id=state.get("merchant_id"),
                customer_id=state.get("customer_id"),
                subscription_id=state.get("subscription_id"),
                payment_id=state.get("payment_id"),
                metadata={
                    "source": "subscription_recovery_agent",
                    "request_fields": {k: v for k, v in self._run_payload(state).items() if v is not None},
                },
            )
            self._record_event(
                session,
                agent_run.run_id,
                1,
                "agent_started",
                payload=self._run_payload(state),
                result={"agent_name": AGENT_NAME, "agent_version": AGENT_VERSION},
            )
            return agent_run
        except Exception:
            return None

    def _persist_missing_context(self, session: Session, state: SubscriptionRecoveryState, result: SubscriptionRecoveryState) -> None:
        run_id = state["run_id"]
        outcome = result.get("outcome") or "No action executed: payment context is missing"
        self._record_event(
            session,
            run_id,
            2,
            "agent_failed",
            payload=self._run_payload(state),
            result={"outcome": outcome, "errors": result.get("errors", [])},
            error_text=(result.get("errors") or [None])[0],
        )
        if result.get("errors"):
            fail_agent_run(session, run_id, error_summary=str(result["errors"][0]), outcome=outcome)
        else:
            fail_agent_run(session, run_id, error_summary="Payment context is required before reasoning", outcome=outcome)

    async def _run_with_session(self, state: SubscriptionRecoveryState, session: Session) -> SubscriptionRecoveryState:
        run_id = state["run_id"]
        sequence = 1
        try:
            state["context"] = load_subscription_recovery_context(session, state["payment_id"])
            sequence += 1
            context = state["context"]
            customer_id = context.get("customer", {}).get("id")
            subscription_id = context.get("subscription", {}).get("id")
            try:
                update_agent_run_context(
                    session,
                    run_id,
                    customer_id=customer_id,
                    subscription_id=subscription_id,
                )
            except Exception:
                session.rollback()
            self._record_event(
                session,
                run_id,
                sequence,
                "context_loaded",
                payload=self._run_payload(state),
                result={
                    "payment_id": state.get("payment_id"),
                    "customer_id": customer_id,
                    "subscription_id": subscription_id,
                },
            )
            model = self._model or OpenAIDecisionModel()
            graph = build_subscription_recovery_graph(
                model=model,
                action_executor=ActionExecutor(
                    session,
                    confidence_threshold=get_settings().openai_confidence_threshold,
                ),
            )
            start = time.perf_counter()
            result = await graph.ainvoke(state)
            duration_ms = int((time.perf_counter() - start) * 1000)
            self._persist_instrumentation(session, run_id, result, sequence=sequence, duration_ms=duration_ms)
            return result
        except SubscriptionRecoveryContextNotFoundError as error:
            state["errors"] = [str(error)]
            state["outcome"] = "No action executed: payment context could not be loaded"
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "agent_failed",
                payload=self._run_payload(state),
                result={"outcome": state["outcome"]},
                error_text=str(error),
            )
            fail_agent_run(session, run_id, error_summary=str(error), outcome=state["outcome"])
            return state
        except Exception as error:
            state["errors"] = [f"Agent setup failed: {error}"]
            state["outcome"] = "No action executed: agent configuration failed"
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "agent_failed",
                payload=self._run_payload(state),
                result={"outcome": state["outcome"]},
                error_text=str(error),
            )
            fail_agent_run(session, run_id, error_summary=str(error), outcome=state["outcome"])
            return state

    def _persist_instrumentation(
        self,
        session: Session,
        run_id: uuid.UUID,
        result: SubscriptionRecoveryState,
        *,
        sequence: int,
        duration_ms: int,
    ) -> None:
        decision = result.get("decision")
        if decision is not None:
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "decision_generated",
                payload={"payment_id": result.get("payment_id"), "user_request": result.get("user_request")},
                result={
                    "action": decision.action.value,
                    "reason": decision.reason,
                    "confidence": float(decision.confidence),
                },
                duration_ms=duration_ms,
            )
            sequence += 1

        selected_action = result.get("selected_action")
        if selected_action is not None:
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "action_selected",
                payload={"selected_action": selected_action},
                result={"selected_action": selected_action, "outcome": result.get("outcome")},
                duration_ms=duration_ms,
            )
            sequence += 1

        execution_evidence = result.get("execution_evidence") or {}

        policy_evidence = execution_evidence.get("policy")
        if policy_evidence is not None:
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "policy_checked",
                payload={"selected_action": selected_action},
                result=policy_evidence,
                duration_ms=duration_ms,
            )
            sequence += 1

        tool_evidence = execution_evidence.get("tool")
        if tool_evidence is not None:
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "tool_executed",
                payload={
                    "name": tool_evidence.get("name"),
                    "input": tool_evidence.get("input"),
                },
                result={
                    "status": tool_evidence.get("status"),
                    "result": tool_evidence.get("result"),
                },
                error_text=tool_evidence.get("error"),
                duration_ms=duration_ms,
            )
            sequence += 1

        state_change = execution_evidence.get("state_change")
        if state_change is not None:
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "state_changed",
                payload={
                    "entity": state_change.get("entity"),
                    "operation": state_change.get("operation"),
                },
                result={
                    "before": state_change.get("before"),
                    "after": state_change.get("after"),
                },
                duration_ms=duration_ms,
            )
            sequence += 1

        outcome = result.get("outcome")
        if outcome and outcome.startswith("Action rejected:"):
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "action_rejected",
                payload={"selected_action": selected_action},
                result={"outcome": outcome, "errors": result.get("errors", [])},
                error_text=result.get("errors", [None])[0] if result.get("errors") else None,
                duration_ms=duration_ms,
            )
            sequence += 1
        elif outcome and outcome == "Action executed":
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "action_executed",
                payload={"selected_action": selected_action},
                result={"selected_action": selected_action, "outcome": outcome, "action_result": result.get("action_result")},
                duration_ms=duration_ms,
            )
            sequence += 1

        if result.get("errors"):
            fail_agent_run(
                session,
                run_id,
                error_summary=str(result["errors"][0]),
                outcome=outcome,
            )
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "agent_failed",
                payload={"selected_action": selected_action},
                result={"outcome": outcome, "errors": result.get("errors", [])},
                error_text=str(result["errors"][0]),
                duration_ms=duration_ms,
            )
            return

        if outcome is not None:
            complete_agent_run(
                session,
                run_id,
                selected_action=selected_action,
                confidence=result.get("confidence"),
                outcome=outcome,
            )
            self._record_event(
                session,
                run_id,
                sequence + 1,
                "agent_completed",
                payload={"selected_action": selected_action},
                result={"outcome": outcome, "confidence": result.get("confidence")},
                duration_ms=duration_ms,
            )
