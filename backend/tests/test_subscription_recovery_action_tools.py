import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents.subscription_recovery import build_action_tools
from app.simulation import services
from app.simulation.models import (
    Communication,
    Customer,
    LinkStatus,
    Merchant,
    Payment,
    PaymentLink,
    PaymentStatus,
    Refund,
    Subscription,
    SubscriptionStatus,
)


def action_records(session) -> tuple[Customer, Subscription, Payment, Payment, Payment]:
    merchant = Merchant(name="Action Merchant", email="action-merchant@test.local")
    customer = Customer(merchant=merchant, name="Action Customer", email="action-customer@test.local")
    session.add_all([merchant, customer])
    session.flush()
    subscription = Subscription(
        merchant_id=merchant.id,
        customer=customer,
        plan_name="Action Plan",
        amount=Decimal("500.00"),
        currency="INR",
        status=SubscriptionStatus.ACTIVE,
    )
    failed = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("500.00"),
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_code="card_declined",
        attempted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    captured = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("500.00"),
        currency="INR",
        status=PaymentStatus.CAPTURED,
        attempted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    declined = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("500.00"),
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_code="retry_declined",
        attempted_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    session.add_all([subscription, failed, captured, declined])
    session.flush()
    return customer, subscription, failed, captured, declined


def action_tools(session):
    return {item.name: item for item in build_action_tools(session)}


def test_action_tools_are_constructible_with_expected_names(session) -> None:
    assert set(action_tools(session)) == {
        "retry_payment",
        "create_payment_link",
        "send_message",
        "issue_refund",
    }


def test_retry_payment_delegates_rules_and_is_idempotent(session) -> None:
    _, _, failed, _, declined = action_records(session)
    tools = action_tools(session)

    result = tools["retry_payment"].invoke({"payment_id": failed.id, "idempotency_key": "action-retry-1"})
    repeated = tools["retry_payment"].invoke({"payment_id": failed.id, "idempotency_key": "action-retry-1"})
    failed_result = tools["retry_payment"].invoke({"payment_id": declined.id})

    assert result["status"] is PaymentStatus.CAPTURED
    assert repeated["id"] == result["id"]
    assert failed_result["status"] is PaymentStatus.FAILED

    with pytest.raises(services.InvalidOperationError):
        tools["retry_payment"].invoke({"payment_id": result["id"]})


def test_create_payment_link_derives_and_persists_payment_context(session) -> None:
    _, subscription, failed, _, _ = action_records(session)
    result = action_tools(session)["create_payment_link"].invoke(
        {"payment_id": failed.id, "idempotency_key": "action-link-1"}
    )

    link = session.get(PaymentLink, result["id"])
    assert link is not None
    assert link.payment_id == failed.id
    assert link.subscription_id == subscription.id
    assert link.amount == Decimal("500.00")


def test_send_message_persists_communication(session) -> None:
    customer, _, _, _, _ = action_records(session)

    result = action_tools(session)["send_message"].invoke(
        {"customer_id": customer.id, "message": "Please update your payment method.", "idempotency_key": "action-message-1"}
    )

    communication = session.get(Communication, result["id"])
    assert communication is not None
    assert communication.customer_id == customer.id
    assert communication.body == "Please update your payment method."


def test_issue_refund_enforces_financial_rules_and_idempotency(session) -> None:
    _, _, failed, captured, _ = action_records(session)
    tools = action_tools(session)

    result = tools["issue_refund"].invoke(
        {"payment_id": captured.id, "amount": "100.00", "idempotency_key": "action-refund-1"}
    )
    repeated = tools["issue_refund"].invoke(
        {"payment_id": captured.id, "amount": "100.00", "idempotency_key": "action-refund-1"}
    )

    assert result["payment_status"] is PaymentStatus.PARTIALLY_REFUNDED
    assert repeated["refund_id"] == result["refund_id"]
    assert len(list(session.scalars(select(Refund).where(Refund.payment_id == captured.id)))) == 1

    with pytest.raises(services.InvalidOperationError):
        tools["issue_refund"].invoke({"payment_id": captured.id, "amount": "401.00", "idempotency_key": "action-refund-2"})
    with pytest.raises(services.InvalidOperationError):
        tools["issue_refund"].invoke({"payment_id": failed.id, "amount": "1.00", "idempotency_key": "action-refund-3"})
