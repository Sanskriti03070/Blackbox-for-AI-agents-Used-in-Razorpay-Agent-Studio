import hashlib
import secrets
import uuid
from decimal import Decimal
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from app.simulation.models import Communication, Customer, LinkStatus, Payment, PaymentLink, PaymentStatus, Refund, Subscription

class DomainError(Exception): pass
class NotFoundError(DomainError): pass
class InvalidOperationError(DomainError): pass

def _one(session: Session, model: type, value: uuid.UUID):
    result = session.get(model, value)
    if result is None: raise NotFoundError(f"{model.__name__} not found")
    return result
def get_payment(session: Session, payment_id: uuid.UUID) -> Payment: return _one(session, Payment, payment_id)
def get_customer(session: Session, customer_id: uuid.UUID) -> Customer: return _one(session, Customer, customer_id)
def get_subscription(session: Session, subscription_id: uuid.UUID) -> Subscription: return _one(session, Subscription, subscription_id)
def get_payment_history(session: Session, payment_id: uuid.UUID) -> list[Payment]:
    payment = get_payment(session, payment_id)
    clause = Payment.subscription_id == payment.subscription_id if payment.subscription_id else Payment.customer_id == payment.customer_id
    return list(session.scalars(select(Payment).where(clause).order_by(Payment.attempted_at, Payment.id)))
def retry_payment(session: Session, payment_id: uuid.UUID, idempotency_key: str | None = None) -> Payment:
    if idempotency_key:
        existing = session.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))
        if existing: return existing
    original = get_payment(session, payment_id)
    if original.status is not PaymentStatus.FAILED: raise InvalidOperationError("Only failed payments can be retried")
    status = PaymentStatus.FAILED if original.failure_code == "retry_declined" else PaymentStatus.CAPTURED
    retry = Payment(merchant_id=original.merchant_id, customer_id=original.customer_id, subscription_id=original.subscription_id, retry_of_payment_id=original.id, idempotency_key=idempotency_key, amount=original.amount, currency=original.currency, status=status, failure_code="retry_declined" if status is PaymentStatus.FAILED else None)
    session.add(retry); session.flush()
    if status is PaymentStatus.CAPTURED: retry.captured_at = retry.attempted_at
    return retry
def create_payment_link(session: Session, customer_id: uuid.UUID, amount: Decimal, currency: str, payment_id: uuid.UUID | None = None, subscription_id: uuid.UUID | None = None, idempotency_key: str | None = None) -> PaymentLink:
    if idempotency_key:
        token = hashlib.sha256(idempotency_key.encode()).hexdigest()
    else:
        token = secrets.token_urlsafe(24)
    existing = session.scalar(select(PaymentLink).where(PaymentLink.token == token))
    if existing:
        return existing
    _one(session, Customer, customer_id)
    if payment_id: get_payment(session, payment_id)
    if subscription_id: get_subscription(session, subscription_id)
    link = PaymentLink(customer_id=customer_id, payment_id=payment_id, subscription_id=subscription_id, amount=amount, currency=currency.upper(), token=token, status=LinkStatus.ACTIVE)
    session.add(link); session.flush(); return link
def send_message(session: Session, customer_id: uuid.UUID, channel: str, body: str, idempotency_key: str | None = None) -> Communication:
    if idempotency_key:
        existing = session.scalar(select(Communication).where(Communication.idempotency_key == idempotency_key))
        if existing: return existing
    _one(session, Customer, customer_id); item = Communication(customer_id=customer_id, channel=channel, body=body, idempotency_key=idempotency_key); session.add(item); session.flush(); return item
def issue_refund(session: Session, payment_id: uuid.UUID, amount: Decimal, idempotency_key: str | None = None) -> Refund:
    if idempotency_key:
        existing = session.scalar(select(Refund).where(Refund.idempotency_key == idempotency_key))
        if existing: return existing
    payment = session.scalar(select(Payment).where(Payment.id == payment_id).with_for_update())
    if payment is None: raise NotFoundError("Payment not found")
    if payment.status not in {PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED}: raise InvalidOperationError("Payment is not refundable")
    refunded = session.scalar(select(func.coalesce(func.sum(Refund.amount), 0)).where(Refund.payment_id == payment_id))
    if amount <= 0 or amount > payment.amount - Decimal(refunded): raise InvalidOperationError("Refund amount exceeds refundable amount")
    refund = Refund(payment_id=payment_id, amount=amount, currency=payment.currency, idempotency_key=idempotency_key); session.add(refund); session.flush()
    payment.status = PaymentStatus.REFUNDED if amount + Decimal(refunded) == payment.amount else PaymentStatus.PARTIALLY_REFUNDED
    return refund
