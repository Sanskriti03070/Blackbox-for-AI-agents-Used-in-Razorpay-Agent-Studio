import asyncio
import uuid
from decimal import Decimal

import pytest

from app.agents.subscription_recovery import (
    SubscriptionRecoveryAgent,
    SubscriptionRecoveryContextNotFoundError,
    SubscriptionRecoveryRequest,
    load_subscription_recovery_context,
)
from app.simulation.models import Customer, Merchant, Payment, PaymentStatus, Subscription, SubscriptionStatus


def test_agent_can_be_instantiated_and_graph_is_compiled() -> None:
    agent = SubscriptionRecoveryAgent()

    assert agent.graph is not None


def test_minimal_run_returns_extensible_state_without_a_decision() -> None:
    agent = SubscriptionRecoveryAgent()

    result = asyncio.run(agent.run(SubscriptionRecoveryRequest(user_request="Review a failed payment.")))

    assert result["user_request"] == "Review a failed payment."
    assert result["messages"] == []
    assert result["outcome"] == "No action executed: payment context is missing"
    assert result["errors"] == ["Payment context is required before reasoning"]
    assert "selected_action" not in result
    assert "decision_reason" not in result


def payment_with_context(session) -> Payment:
    merchant = Merchant(name="Context Merchant", email="context-merchant@test.local")
    customer = Customer(merchant=merchant, name="Context Customer", email="context-customer@test.local")
    session.add_all([merchant, customer])
    session.flush()
    subscription = Subscription(
        merchant_id=merchant.id,
        customer=customer,
        plan_name="Context Plan",
        amount=Decimal("1200.00"),
        currency="INR",
        status=SubscriptionStatus.PAST_DUE,
    )
    previous = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("1200.00"),
        currency="INR",
        status=PaymentStatus.CAPTURED,
    )
    failed = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("1200.00"),
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_code="card_declined",
    )
    session.add_all([subscription, previous, failed])
    session.flush()
    return failed


def test_context_loader_returns_payment_customer_subscription_and_history(session) -> None:
    payment = payment_with_context(session)

    context = load_subscription_recovery_context(session, payment.id)

    assert context["payment"]["id"] == payment.id
    assert context["payment"]["status"] is PaymentStatus.FAILED
    assert context["customer"]["name"] == "Context Customer"
    assert context["subscription"] is not None
    assert context["subscription"]["plan_name"] == "Context Plan"
    assert len(context["payment_history"]) == 2


def test_agent_loads_context_before_running_graph(session) -> None:
    payment = payment_with_context(session)
    agent = SubscriptionRecoveryAgent(session=session)

    result = asyncio.run(agent.run(SubscriptionRecoveryRequest(user_request="Review payment.", payment_id=payment.id)))

    assert result["context"]["payment"]["id"] == payment.id
    assert result["context"]["payment_history"]


def test_missing_payment_context_raises_clear_error(session) -> None:
    with pytest.raises(SubscriptionRecoveryContextNotFoundError, match="Payment not found"):
        load_subscription_recovery_context(session, uuid.uuid4())
