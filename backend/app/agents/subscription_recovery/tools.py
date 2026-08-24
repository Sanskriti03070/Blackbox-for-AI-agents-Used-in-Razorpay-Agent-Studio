import uuid

from langchain_core.tools import BaseTool, tool
from sqlalchemy.orm import Session

from app.agents.subscription_recovery.state import (
    CustomerContext,
    PaymentContext,
    PaymentHistoryItem,
    SubscriptionContext,
)
from app.simulation import services


def build_read_only_tools(session: Session) -> list[BaseTool]:
    """Create database-backed read-only tools for future LangGraph tool calling."""

    @tool
    def get_payment(payment_id: uuid.UUID) -> PaymentContext:
        """Get a payment by ID, including its amount, status, failure information, and timestamps."""
        payment = services.get_payment(session, payment_id)
        return {
            "id": payment.id,
            "amount": payment.amount,
            "currency": payment.currency,
            "status": payment.status,
            "failure_code": payment.failure_code,
            "attempted_at": payment.attempted_at,
            "captured_at": payment.captured_at,
        }

    @tool
    def get_customer(customer_id: uuid.UUID) -> CustomerContext:
        """Get a customer by ID, returning the minimal identity information for recovery context."""
        customer = services.get_customer(session, customer_id)
        return {"id": customer.id, "name": customer.name}

    @tool
    def get_subscription(subscription_id: uuid.UUID) -> SubscriptionContext:
        """Get a subscription by ID, including lifecycle status and billing information."""
        subscription = services.get_subscription(session, subscription_id)
        return {
            "id": subscription.id,
            "status": subscription.status,
            "plan_name": subscription.plan_name,
            "amount": subscription.amount,
            "currency": subscription.currency,
        }

    @tool
    def get_payment_history(payment_id: uuid.UUID) -> list[PaymentHistoryItem]:
        """Get persisted payment attempts for the payment's subscription or customer in chronological order."""
        return [
            {
                "id": item.id,
                "status": item.status,
                "amount": item.amount,
                "attempted_at": item.attempted_at,
            }
            for item in services.get_payment_history(session, payment_id)
        ]

    return [get_payment, get_customer, get_subscription, get_payment_history]
