from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.agents.subscription_recovery.state import SubscriptionRecoveryContext


class RecoveryAction(str, enum.Enum):
    RETRY_PAYMENT = "retry_payment"
    CREATE_PAYMENT_LINK = "create_payment_link"
    SEND_MESSAGE = "send_message"
    ISSUE_REFUND = "issue_refund"
    ESCALATE = "escalate"


class StructuredDecision(BaseModel):
    """Schema enforced at the model boundary and validated again before action."""

    model_config = ConfigDict(extra="forbid")

    action: RecoveryAction
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class DecisionModel(Protocol):
    def decide(self, user_request: str, context: SubscriptionRecoveryContext) -> StructuredDecision:
        """Return one schema-valid recovery decision."""
