from langchain_core.tools import ToolException
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agents.subscription_recovery.action_tools import build_action_tools
from app.agents.subscription_recovery.decision import RecoveryAction, StructuredDecision
from app.agents.subscription_recovery.state import SubscriptionRecoveryState
from app.simulation import services
from app.simulation.models import PaymentStatus


class ActionExecutor:
    """Deterministic allowlisted action dispatcher with financial safety checks."""

    def __init__(self, session: Session, confidence_threshold: float = 0.7) -> None:
        self._tools = {item.name: item for item in build_action_tools(session)}
        self._confidence_threshold = confidence_threshold

    def execute(self, decision: StructuredDecision, state: SubscriptionRecoveryState) -> dict[str, Any]:
        context = state.get("context")
        if context is None:
            return {"selected_action": RecoveryAction.ESCALATE.value, "outcome": "Escalated: payment context is required"}

        if decision.confidence < self._confidence_threshold:
            return {
                "selected_action": RecoveryAction.ESCALATE.value,
                "decision_reason": f"Low confidence ({decision.confidence:.2f}); {decision.reason}",
                "outcome": "Escalated: decision confidence below threshold",
            }

        action = decision.action
        if action is RecoveryAction.ESCALATE:
            return {"selected_action": action.value, "outcome": "Escalated for human review"}

        payment_id = context["payment"]["id"]
        try:
            key = f"subscription-recovery:{payment_id}:{action.value}"
            if action is RecoveryAction.RETRY_PAYMENT:
                result = self._tools["retry_payment"].invoke({"payment_id": payment_id, "idempotency_key": key})
            elif action is RecoveryAction.CREATE_PAYMENT_LINK:
                result = self._tools["create_payment_link"].invoke({"payment_id": payment_id, "idempotency_key": key})
            elif action is RecoveryAction.SEND_MESSAGE:
                result = self._tools["send_message"].invoke({"customer_id": context["customer"]["id"], "message": state.get("user_request", "Payment recovery requires attention."), "idempotency_key": key})
            elif action is RecoveryAction.ISSUE_REFUND:
                if context["payment"]["status"] not in {PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED}:
                    raise services.InvalidOperationError("Payment is not refundable")
                result = self._tools["issue_refund"].invoke({"payment_id": payment_id, "amount": context["payment"]["amount"], "idempotency_key": key})
            else:
                raise services.InvalidOperationError("Unsupported recovery action")
        except (services.DomainError, ToolException) as error:
            return {"selected_action": action.value, "outcome": f"Action rejected: {error}", "errors": [str(error)]}
        return {"selected_action": action.value, "outcome": "Action executed", "action_result": result}
