import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.agents.subscription_recovery.state import SubscriptionRecoveryContext
from app.simulation import services
from app.simulation.models import Payment


class SubscriptionRecoveryContextNotFoundError(Exception):
    """Raised when a payment cannot provide recovery context."""


def load_subscription_recovery_context(
    session: Session, payment_id: uuid.UUID
) -> SubscriptionRecoveryContext:
    """Load the minimum persisted context needed for later recovery reasoning."""
    payment = session.scalar(
        select(Payment)
        .options(selectinload(Payment.customer), selectinload(Payment.subscription))
        .where(Payment.id == payment_id)
    )
    if payment is None:
        raise SubscriptionRecoveryContextNotFoundError("Payment not found")

    history = services.get_payment_history(session, payment.id)
    subscription = payment.subscription
    return {
        "payment": {
            "id": payment.id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "failure_code": payment.failure_code,
            "attempted_at": payment.attempted_at,
            "captured_at": payment.captured_at,
        },
        "customer": {"id": payment.customer.id, "name": payment.customer.name},
        "subscription": None
        if subscription is None
        else {
            "id": subscription.id,
            "status": subscription.status,
            "plan_name": subscription.plan_name,
            "amount": subscription.amount,
            "currency": subscription.currency,
        },
        "payment_history": [
            {
                "id": item.id,
                "status": item.status,
                "amount": item.amount,
                "attempted_at": item.attempted_at,
            }
            for item in history
        ],
    }
