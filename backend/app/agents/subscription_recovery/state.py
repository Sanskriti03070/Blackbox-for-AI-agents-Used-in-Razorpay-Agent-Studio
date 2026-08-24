import uuid
from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from app.agents.subscription_recovery.decision import StructuredDecision
from app.simulation.models import PaymentStatus, SubscriptionStatus


class PaymentHistoryItem(TypedDict):
    id: uuid.UUID
    status: PaymentStatus
    amount: Decimal
    attempted_at: datetime


class PaymentContext(TypedDict):
    id: uuid.UUID
    amount: Decimal
    currency: str
    status: PaymentStatus
    failure_code: str | None
    attempted_at: datetime
    captured_at: datetime | None


class CustomerContext(TypedDict):
    id: uuid.UUID
    name: str


class SubscriptionContext(TypedDict):
    id: uuid.UUID
    status: SubscriptionStatus
    plan_name: str
    amount: Decimal
    currency: str


class SubscriptionRecoveryContext(TypedDict):
    payment: PaymentContext
    customer: CustomerContext
    subscription: SubscriptionContext | None
    payment_history: list[PaymentHistoryItem]


class SubscriptionRecoveryState(TypedDict, total=False):
    """Extensible state contract for one subscription-recovery execution."""

    run_id: uuid.UUID
    merchant_id: uuid.UUID
    customer_id: uuid.UUID
    subscription_id: uuid.UUID
    payment_id: uuid.UUID
    user_request: str
    context: SubscriptionRecoveryContext
    decision: StructuredDecision
    confidence: float | None
    messages: list[str]
    selected_action: str | None
    action_result: object | None
    decision_reason: str | None
    outcome: str | None
    errors: list[str]
