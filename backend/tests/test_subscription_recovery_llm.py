import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from app.agents.models import AgentRunStatus
from app.agents.repository import get_agent_run, get_agent_trace
from app.agents.subscription_recovery import SubscriptionRecoveryAgent, SubscriptionRecoveryRequest
from app.agents.subscription_recovery.decision import RecoveryAction, StructuredDecision
from app.simulation.models import Customer, Merchant, Payment, PaymentStatus, Subscription, SubscriptionStatus


class FakeDecisionModel:
    def __init__(self, decision: Any = None, error: Exception | None = None) -> None:
        self.decision = decision
        self.error = error

    def decide(self, user_request, context):
        if self.error:
            raise self.error
        return self.decision


def records(session) -> tuple[Customer, Subscription, Payment, Payment]:
    merchant = Merchant(name="LLM Merchant", email="llm-merchant@test.local")
    customer = Customer(merchant=merchant, name="LLM Customer", email="llm-customer@test.local")
    session.add_all([merchant, customer])
    session.flush()
    subscription = Subscription(
        merchant_id=merchant.id,
        customer=customer,
        plan_name="LLM Plan",
        amount=Decimal("100.00"),
        currency="INR",
        status=SubscriptionStatus.PAST_DUE,
    )
    failed = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("100.00"),
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_code="card_declined",
        attempted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    captured = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("100.00"),
        currency="INR",
        status=PaymentStatus.CAPTURED,
        attempted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    session.add_all([subscription, failed, captured])
    session.flush()
    return customer, subscription, failed, captured


def decision(action: RecoveryAction, confidence: float = 0.95) -> StructuredDecision:
    return StructuredDecision(action=action, reason=f"Use {action.value} based on context", confidence=confidence)


def run(session, payment: Payment | None, model: Any):
    return asyncio.run(
        SubscriptionRecoveryAgent(session=session, model=model).run(
            SubscriptionRecoveryRequest(
                user_request="Recover this subscription payment.",
                payment_id=payment.id if payment else None,
            )
        )
    )


def test_structured_decision_parsing() -> None:
    parsed = StructuredDecision.model_validate({"action": "retry_payment", "reason": "Retry is appropriate", "confidence": 0.8})

    assert parsed.action is RecoveryAction.RETRY_PAYMENT
    assert parsed.confidence == 0.8


@pytest.mark.parametrize("action", [RecoveryAction.RETRY_PAYMENT, RecoveryAction.CREATE_PAYMENT_LINK, RecoveryAction.SEND_MESSAGE])
def test_recovery_actions_execute_from_structured_decision(session, action: RecoveryAction) -> None:
    customer, _, failed, _ = records(session)
    result = run(session, failed, FakeDecisionModel(decision(action)))

    assert result["selected_action"] == action.value
    assert result["outcome"] == "Action executed"
    assert result["context"]["customer"]["id"] == customer.id


def test_issue_refund_decision_executes_and_returns_outcome(session) -> None:
    _, _, _, captured = records(session)

    result = run(session, captured, FakeDecisionModel(decision(RecoveryAction.ISSUE_REFUND)))

    assert result["selected_action"] == "issue_refund"
    assert result["outcome"] == "Action executed"
    assert result["action_result"]["payment_status"] is PaymentStatus.REFUNDED


def test_escalate_decision_performs_no_financial_action(session) -> None:
    _, _, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel(decision(RecoveryAction.ESCALATE)))

    assert result["selected_action"] == "escalate"
    assert result["outcome"] == "Escalated for human review"


def test_low_confidence_decision_becomes_escalation(session) -> None:
    _, _, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel(decision(RecoveryAction.RETRY_PAYMENT, confidence=0.2)))

    assert result["selected_action"] == "escalate"
    assert "below threshold" in result["outcome"]


def test_unsupported_action_is_rejected_without_financial_action(session) -> None:
    _, _, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel({"action": "delete_payment", "reason": "bad", "confidence": 1.0}))

    assert result["outcome"] == "No action executed: decision generation failed"
    assert "Decision model failed" in result["errors"][0]


def test_missing_context_prevents_financial_action() -> None:
    result = run(None, None, FakeDecisionModel(decision(RecoveryAction.RETRY_PAYMENT)))

    assert result["outcome"] == "No action executed: payment context is missing"
    assert result["errors"] == ["Payment context is required before reasoning"]


def test_domain_refund_validation_still_applies(session) -> None:
    _, _, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel(decision(RecoveryAction.ISSUE_REFUND)))

    assert result["selected_action"] == "issue_refund"
    assert result["outcome"].startswith("Action rejected:")
    assert result["errors"]


def test_agent_run_and_trace_persistence_for_successful_execution(session) -> None:
    customer, _, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel(decision(RecoveryAction.RETRY_PAYMENT)))

    persisted = get_agent_run(session, result["run_id"])
    assert persisted is not None
    assert persisted.agent_name == "subscription_recovery"
    assert persisted.customer_id == customer.id
    assert persisted.payment_id == failed.id
    assert persisted.status == AgentRunStatus.COMPLETED.value
    assert persisted.selected_action == "retry_payment"
    assert persisted.confidence == 0.95
    assert persisted.outcome == "Action executed"

    events = get_agent_trace(session, persisted.run_id)
    assert [event.sequence for event in events][:6] == [1, 2, 3, 4, 5, 6]
    assert {event.event_type for event in events} >= {
        "agent_started",
        "context_loaded",
        "decision_generated",
        "action_selected",
        "action_executed",
        "agent_completed",
    }
    serialized = json.dumps([{"payload": event.payload, "result": event.result, "error_text": event.error_text} for event in events])
    assert "api_key" not in serialized.lower()
    assert "authorization" not in serialized.lower()
    assert "card_number" not in serialized.lower()
def test_successful_execution_persists_forensic_evidence_events(session) -> None:
    customer, subscription, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel(decision(RecoveryAction.RETRY_PAYMENT)))

    events = get_agent_trace(session, result["run_id"])
    event_types = [event.event_type for event in events]

    assert "policy_checked" in event_types
    assert "tool_executed" in event_types
    assert "state_changed" in event_types

    policy_event = next(e for e in events if e.event_type == "policy_checked")
    assert policy_event.result["allowed"] is True
    assert policy_event.result["confidence"] == 0.95

    tool_event = next(e for e in events if e.event_type == "tool_executed")
    assert tool_event.result["status"] == "executed"
    assert tool_event.payload["name"] == "retry_payment"

    state_event = next(e for e in events if e.event_type == "state_changed")
    assert state_event.result["before"]["status"] == "failed"
    assert state_event.result["after"]["status"] == "captured"


def test_rejected_refund_persists_forensic_evidence_without_state_change(session) -> None:
    _, _, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel(decision(RecoveryAction.ISSUE_REFUND)))

    events = get_agent_trace(session, result["run_id"])
    event_types = [event.event_type for event in events]

    assert "policy_checked" in event_types
    assert "tool_executed" in event_types
    assert "state_changed" not in event_types

    tool_event = next(e for e in events if e.event_type == "tool_executed")
    assert tool_event.result["status"] == "rejected"
    assert tool_event.error_text == "Payment is not refundable"

def test_agent_failure_and_missing_context_are_persisted(session) -> None:
    result = run(None, None, FakeDecisionModel(decision(RecoveryAction.RETRY_PAYMENT)))

    persisted = get_agent_run(session, result["run_id"])
    assert persisted is not None
    assert persisted.status == AgentRunStatus.FAILED.value
    assert persisted.outcome == "No action executed: payment context is missing"
    assert persisted.error_summary == "Payment context is required before reasoning"

    events = get_agent_trace(session, persisted.run_id)
    assert any(event.event_type == "agent_failed" for event in events)
    assert any(event.error_text == "Payment context is required before reasoning" for event in events)


def test_rejected_action_is_recorded_and_not_secret_sensitive(session) -> None:
    _, _, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel(decision(RecoveryAction.ISSUE_REFUND)))

    persisted = get_agent_run(session, result["run_id"])
    assert persisted is not None
    assert persisted.status == AgentRunStatus.FAILED.value or persisted.status == AgentRunStatus.COMPLETED.value
    assert persisted.outcome is not None

    events = get_agent_trace(session, persisted.run_id)
    assert any(event.event_type == "action_rejected" for event in events) or any(event.event_type == "agent_failed" for event in events)
    serialized = json.dumps([{"payload": event.payload, "result": event.result, "error_text": event.error_text} for event in events])
    assert "secret" not in serialized.lower()
    assert "cvv" not in serialized.lower()


def test_model_failure_becomes_safe_failure(session) -> None:
    _, _, failed, _ = records(session)

    result = run(session, failed, FakeDecisionModel(error=RuntimeError("provider unavailable")))

    assert result["outcome"] == "No action executed: decision generation failed"
    assert "provider unavailable" in result["errors"][0]

    persisted = get_agent_run(session, result["run_id"])
    assert persisted is not None
    assert persisted.status == AgentRunStatus.FAILED.value
    assert "provider unavailable" in persisted.error_summary
