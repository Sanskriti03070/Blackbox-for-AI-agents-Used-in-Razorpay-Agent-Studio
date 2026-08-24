import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents.models import AgentRun, AgentRunStatus, AgentTraceEvent
from app.agents.repository import (
    append_trace_event,
    complete_agent_run,
    create_agent_run,
    fail_agent_run,
    get_agent_run,
    get_agent_trace,
)
from app.simulation.models import Customer, Merchant, Payment, PaymentStatus, Subscription, SubscriptionStatus


def make_customer_context(session):
    merchant = Merchant(name="Trace Merchant", email="trace-merchant@test.local")
    customer = Customer(merchant=merchant, name="Trace Customer", email="trace-customer@test.local")
    session.add_all([merchant, customer])
    session.flush()

    subscription = Subscription(
        merchant_id=merchant.id,
        customer=customer,
        plan_name="Trace Plan",
        amount=Decimal("250.00"),
        currency="INR",
        status=SubscriptionStatus.PAST_DUE,
    )
    payment = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("250.00"),
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_code="card_declined",
    )
    session.add_all([subscription, payment])
    session.flush()
    return merchant, customer, subscription, payment


def test_agent_run_creation_and_completion_persists_expected_fields(session):
    merchant, customer, subscription, payment = make_customer_context(session)

    run = create_agent_run(
        session,
        agent_name="subscription_recovery",
        agent_version="1.0.0",
        user_request="Review a failed payment.",
        merchant_id=merchant.id,
        customer_id=customer.id,
        subscription_id=subscription.id,
        payment_id=payment.id,
        metadata={"source": "phase7a-test"},
    )

    assert run.status == AgentRunStatus.STARTED.value
    assert run.user_request == "Review a failed payment."
    assert run.metadata_ == {"source": "phase7a-test"}

    completed = complete_agent_run(
        session,
        run.run_id,
        selected_action="retry_payment",
        confidence=0.91,
        outcome="payment retried",
    )

    assert completed.status == AgentRunStatus.COMPLETED.value
    assert completed.selected_action == "retry_payment"
    assert completed.confidence == 0.91
    assert completed.outcome == "payment retried"
    assert completed.completed_at is not None

    persisted = get_agent_run(session, run.run_id)
    assert persisted is not None
    assert persisted.status == AgentRunStatus.COMPLETED.value


def test_agent_trace_events_order_by_sequence_and_retrieve_run_events(session):
    merchant, customer, subscription, payment = make_customer_context(session)

    run = create_agent_run(
        session,
        agent_name="subscription_recovery",
        agent_version="1.0.0",
        user_request="Trace the recovery flow.",
        merchant_id=merchant.id,
        customer_id=customer.id,
        subscription_id=subscription.id,
        payment_id=payment.id,
    )

    append_trace_event(
        session,
        run.run_id,
        sequence=1,
        source="decision_model",
        event_type="model_input",
        payload={"context_loaded": True},
    )
    append_trace_event(
        session,
        run.run_id,
        sequence=2,
        source="action_tool",
        event_type="tool_invocation",
        payload={"tool": "retry_payment"},
        result={"status": "ok"},
    )
    append_trace_event(
        session,
        run.run_id,
        sequence=3,
        source="executor",
        event_type="finalized",
        payload={"outcome": "done"},
        duration_ms=42,
    )

    events = get_agent_trace(session, run.run_id)
    assert [event.sequence for event in events] == [1, 2, 3]
    assert events[0].source == "decision_model"
    assert events[1].result == {"status": "ok"}
    assert events[2].duration_ms == 42

    stored_run = get_agent_run(session, run.run_id)
    assert stored_run is not None
    assert len(stored_run.events) == 3


def test_agent_run_failure_persists_error_and_fk_relationships(session):
    merchant, customer, subscription, payment = make_customer_context(session)

    run = create_agent_run(
        session,
        agent_name="subscription_recovery",
        agent_version="1.1.0",
        user_request="Check payment recovery failure.",
        merchant_id=merchant.id,
        customer_id=customer.id,
        subscription_id=subscription.id,
        payment_id=payment.id,
    )

    fail_agent_run(
        session,
        run.run_id,
        error_summary="required context missing",
        outcome="No action executed: missing payment context",
    )

    persisted = session.scalar(select(AgentRun).where(AgentRun.run_id == run.run_id))
    assert persisted is not None
    assert persisted.status == AgentRunStatus.FAILED.value
    assert persisted.error_summary == "required context missing"
    assert persisted.customer_id == customer.id
    assert persisted.payment_id == payment.id
    assert persisted.subscription_id == subscription.id

    no_trace = session.scalar(select(AgentTraceEvent).where(AgentTraceEvent.run_id == run.run_id))
    assert no_trace is None

    event = append_trace_event(
        session,
        run.run_id,
        sequence=1,
        source="error_handler",
        event_type="failure_recorded",
        error_text="required context missing",
    )

    assert event.run_id == run.run_id
    assert event.sequence == 1

    trace = get_agent_trace(session, run.run_id)
    assert len(trace) == 1
    assert trace[0].error_text == "required context missing"


def test_agent_trace_events_are_unique_per_run_sequence(session):
    merchant, customer, subscription, payment = make_customer_context(session)

    run = create_agent_run(
        session,
        agent_name="subscription_recovery",
        agent_version="1.0.0",
        user_request="Ensure sequence ordering is deterministic.",
        merchant_id=merchant.id,
        customer_id=customer.id,
        subscription_id=subscription.id,
        payment_id=payment.id,
    )

    append_trace_event(session, run.run_id, sequence=1, source="a", event_type="start")

    with pytest.raises(Exception):
        append_trace_event(session, run.run_id, sequence=1, source="b", event_type="duplicate")
