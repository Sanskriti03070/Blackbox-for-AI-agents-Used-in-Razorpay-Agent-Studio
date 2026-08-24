import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.agents.subscription_recovery import build_read_only_tools
from app.simulation import services
from app.simulation.models import Customer, Merchant, Payment, PaymentStatus, Subscription, SubscriptionStatus


def payment_records(session) -> tuple[Customer, Subscription, Payment]:
    merchant = Merchant(name="Tool Merchant", email="tool-merchant@test.local")
    customer = Customer(merchant=merchant, name="Tool Customer", email="tool-customer@test.local")
    session.add_all([merchant, customer])
    session.flush()
    subscription = Subscription(
        merchant_id=merchant.id,
        customer=customer,
        plan_name="Tool Plan",
        amount=Decimal("2500.00"),
        currency="INR",
        status=SubscriptionStatus.PAST_DUE,
    )
    previous = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("2500.00"),
        currency="INR",
        status=PaymentStatus.CAPTURED,
        attempted_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    failed = Payment(
        merchant_id=merchant.id,
        customer=customer,
        subscription=subscription,
        amount=Decimal("2500.00"),
        currency="INR",
        status=PaymentStatus.FAILED,
        failure_code="card_declined",
        attempted_at=datetime.now(timezone.utc),
    )
    session.add_all([subscription, previous, failed])
    session.flush()
    return customer, subscription, failed


def test_read_only_tools_return_persisted_entities_and_history(session) -> None:
    customer, subscription, payment = payment_records(session)
    tools = {item.name: item for item in build_read_only_tools(session)}

    assert set(tools) == {"get_payment", "get_customer", "get_subscription", "get_payment_history"}
    assert tools["get_payment"].invoke({"payment_id": payment.id})["id"] == payment.id
    assert tools["get_customer"].invoke({"customer_id": customer.id})["name"] == "Tool Customer"
    assert tools["get_subscription"].invoke({"subscription_id": subscription.id})["plan_name"] == "Tool Plan"
    history = tools["get_payment_history"].invoke({"payment_id": payment.id})
    assert [item["status"] for item in history] == [PaymentStatus.CAPTURED, PaymentStatus.FAILED]


@pytest.mark.parametrize("name, argument", [
    ("get_payment", "payment_id"),
    ("get_customer", "customer_id"),
    ("get_subscription", "subscription_id"),
])
def test_tools_raise_existing_domain_error_for_missing_resources(session, name: str, argument: str) -> None:
    tool_by_name = {item.name: item for item in build_read_only_tools(session)}[name]

    with pytest.raises(services.NotFoundError):
        tool_by_name.invoke({argument: uuid.uuid4()})
