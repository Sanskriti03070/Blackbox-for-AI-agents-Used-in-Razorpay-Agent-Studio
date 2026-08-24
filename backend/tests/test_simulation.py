from decimal import Decimal
from app.simulation import services
from app.simulation.models import Customer, Merchant, Payment, PaymentStatus, Subscription, SubscriptionStatus

def records(session):
    merchant = Merchant(name="Test Merchant", email="merchant@test.local")
    customer = Customer(merchant=merchant, name="Test Customer", email="customer@test.local")
    session.add_all([merchant, customer]); session.flush()
    subscription = Subscription(merchant_id=merchant.id, customer=customer, plan_name="Plan", amount=Decimal("100.00"), currency="INR", status=SubscriptionStatus.ACTIVE)
    captured = Payment(merchant_id=merchant.id, customer=customer, subscription=subscription, amount=Decimal("100.00"), currency="INR", status=PaymentStatus.CAPTURED)
    failed = Payment(merchant_id=merchant.id, customer=customer, subscription=subscription, amount=Decimal("100.00"), currency="INR", status=PaymentStatus.FAILED, failure_code="card_declined")
    declined = Payment(merchant_id=merchant.id, customer=customer, subscription=subscription, amount=Decimal("100.00"), currency="INR", status=PaymentStatus.FAILED, failure_code="retry_declined")
    session.add_all([subscription, captured, failed, declined]); session.flush(); return customer, subscription, captured, failed, declined

def test_entity_relationships_and_payment_creation(session):
    customer, subscription, captured, _, _ = records(session)
    assert captured.subscription is subscription
    assert subscription.customer is customer
    assert customer.merchant.customers == [customer]

def test_failed_payment_retrieval_and_history(session):
    _, _, _, failed, _ = records(session)
    assert services.get_payment(session, failed.id).status is PaymentStatus.FAILED
    assert len(services.get_payment_history(session, failed.id)) == 3

def test_retry_success_failure_and_idempotency(session):
    _, _, _, failed, declined = records(session)
    retry = services.retry_payment(session, failed.id, "retry-1")
    assert retry.status is PaymentStatus.CAPTURED and retry.retry_of_payment_id == failed.id
    assert services.retry_payment(session, failed.id, "retry-1").id == retry.id
    assert services.retry_payment(session, declined.id).status is PaymentStatus.FAILED

def test_payment_link_and_message_creation(session):
    customer, subscription, _, failed, _ = records(session)
    link = services.create_payment_link(session, customer.id, Decimal("100.00"), "INR", failed.id, subscription.id, "link-1")
    assert link.customer_id == customer.id
    message = services.send_message(session, customer.id, "email", "Please update payment", "message-1")
    assert message.status == "sent" and services.send_message(session, customer.id, "email", "ignored", "message-1").id == message.id

def test_refund_rules_and_idempotency(session):
    _, _, captured, failed, _ = records(session)
    refund = services.issue_refund(session, captured.id, Decimal("40.00"), "refund-1")
    assert refund.amount == Decimal("40.00") and captured.status is PaymentStatus.PARTIALLY_REFUNDED
    assert services.issue_refund(session, captured.id, Decimal("40.00"), "refund-1").id == refund.id
    try: services.issue_refund(session, captured.id, Decimal("70.00"))
    except services.InvalidOperationError: pass
    else: raise AssertionError("over-refund should fail")
    try: services.issue_refund(session, failed.id, Decimal("1.00"))
    except services.InvalidOperationError: pass
    else: raise AssertionError("failed payment refund should fail")
