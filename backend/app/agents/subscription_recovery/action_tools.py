import uuid
from decimal import Decimal
from typing import TypedDict

from langchain_core.tools import BaseTool, tool
from sqlalchemy.orm import Session

from app.agents.subscription_recovery.state import PaymentContext
from app.simulation import services
from app.simulation.models import PaymentStatus


class PaymentLinkResult(TypedDict):
    id: uuid.UUID
    customer_id: uuid.UUID
    payment_id: uuid.UUID | None
    subscription_id: uuid.UUID | None
    token: str
    amount: Decimal
    currency: str
    status: str


class CommunicationResult(TypedDict):
    id: uuid.UUID
    customer_id: uuid.UUID
    channel: str
    body: str
    status: str


class RefundResult(TypedDict):
    refund_id: uuid.UUID
    payment_id: uuid.UUID
    amount: Decimal
    currency: str
    payment_status: PaymentStatus


def _payment_context(payment) -> PaymentContext:
    return {
        "id": payment.id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status,
        "failure_code": payment.failure_code,
        "attempted_at": payment.attempted_at,
        "captured_at": payment.captured_at,
    }


def build_action_tools(session: Session) -> list[BaseTool]:
    """Create database-backed action adapters for future LangGraph tool calling."""

    @tool
    def retry_payment(payment_id: uuid.UUID, idempotency_key: str | None = None) -> PaymentContext:
        """Retry an eligible failed payment using deterministic simulation rules; never retry a non-failed payment."""
        payment = services.retry_payment(session, payment_id, idempotency_key)
        return _payment_context(payment)

    @tool
    def create_payment_link(
        payment_id: uuid.UUID,
        amount: Decimal | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentLinkResult:
        """Create a persisted payment link for a referenced payment, defaulting to that payment's amount; repeated idempotency keys reuse the link."""
        payment = services.get_payment(session, payment_id)
        link = services.create_payment_link(
            session,
            customer_id=payment.customer_id,
            amount=amount if amount is not None else payment.amount,
            currency=payment.currency,
            payment_id=payment.id,
            subscription_id=payment.subscription_id,
            idempotency_key=idempotency_key,
        )
        return {
            "id": link.id,
            "customer_id": link.customer_id,
            "payment_id": link.payment_id,
            "subscription_id": link.subscription_id,
            "token": link.token,
            "amount": link.amount,
            "currency": link.currency,
            "status": link.status.value,
        }

    @tool
    def send_message(
        customer_id: uuid.UUID,
        message: str,
        idempotency_key: str | None = None,
    ) -> CommunicationResult:
        """Persist a recovery message for a customer; this local simulation sends no external communication."""
        communication = services.send_message(
            session,
            customer_id=customer_id,
            channel="email",
            body=message,
            idempotency_key=idempotency_key,
        )
        return {
            "id": communication.id,
            "customer_id": communication.customer_id,
            "channel": communication.channel,
            "body": communication.body,
            "status": communication.status,
        }

    @tool
    def issue_refund(
        payment_id: uuid.UUID,
        amount: Decimal,
        idempotency_key: str,
    ) -> RefundResult:
        """Issue a financial refund only for a refundable payment and never above its remaining refundable amount; an idempotency key is required."""
        if not idempotency_key:
            raise services.InvalidOperationError("Refund idempotency_key is required")
        refund = services.issue_refund(session, payment_id, amount, idempotency_key)
        payment = services.get_payment(session, payment_id)
        return {
            "refund_id": refund.id,
            "payment_id": refund.payment_id,
            "amount": refund.amount,
            "currency": refund.currency,
            "payment_status": payment.status,
        }

    return [retry_payment, create_payment_link, send_message, issue_refund]
