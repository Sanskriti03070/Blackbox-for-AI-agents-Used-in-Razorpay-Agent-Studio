from typing import Any

from langchain_core.tools import ToolException
from sqlalchemy.orm import Session

from app.agents.subscription_recovery.action_tools import build_action_tools
from app.agents.subscription_recovery.decision import RecoveryAction, StructuredDecision
from app.agents.subscription_recovery.state import SubscriptionRecoveryState
from app.simulation import services
from app.simulation.models import PaymentStatus


def _json_safe(value: Any) -> Any:
    """
    Convert database/domain values into JSON-safe values for Black Box evidence.

    Trace evidence is persisted to PostgreSQL JSONB, so UUIDs, Decimals,
    enums, and nested structures must be converted before persistence.
    """
    if value is None:
        return None

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]

    if hasattr(value, "value"):
        return _json_safe(value.value)

    if hasattr(value, "isoformat"):
        return value.isoformat()

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


class ActionExecutor:
    """Deterministic allowlisted action dispatcher with financial safety checks."""

    def __init__(
        self,
        session: Session,
        confidence_threshold: float = 0.7,
    ) -> None:
        self._session = session
        self._tools = {
            item.name: item
            for item in build_action_tools(session)
        }
        self._confidence_threshold = confidence_threshold

    def execute(
        self,
        decision: StructuredDecision,
        state: SubscriptionRecoveryState,
    ) -> dict[str, Any]:
        """
        Execute one allowlisted recovery action.

        In addition to the normal agent result, this returns `execution_evidence`
        containing the facts Black Box needs to reconstruct what happened:

        - policy evaluation
        - selected action
        - tool invocation
        - state change
        """

        context = state.get("context")

        # ---------------------------------------------------------
        # 1. No payment context
        # ---------------------------------------------------------
        if context is None:
            return {
                "selected_action": RecoveryAction.ESCALATE.value,
                "outcome": "Escalated: payment context is required",
                "execution_evidence": {
                    "policy": {
                        "confidence": float(decision.confidence),
                        "threshold": self._confidence_threshold,
                        "allowed": False,
                        "reason": "payment_context_missing",
                    }
                },
            }

        # ---------------------------------------------------------
        # 2. Policy / confidence evaluation
        # ---------------------------------------------------------
        policy_evidence: dict[str, Any] = {
            "confidence": float(decision.confidence),
            "threshold": self._confidence_threshold,
            "allowed": decision.confidence >= self._confidence_threshold,
            "reason": decision.reason,
        }

        if decision.confidence < self._confidence_threshold:
            policy_evidence["reason"] = "confidence_below_threshold"

            return {
                "selected_action": RecoveryAction.ESCALATE.value,
                "decision_reason": (
                    f"Low confidence ({decision.confidence:.2f}); "
                    f"{decision.reason}"
                ),
                "outcome": "Escalated: decision confidence below threshold",
                "execution_evidence": {
                    "policy": policy_evidence,
                },
            }

        # ---------------------------------------------------------
        # 3. Agent explicitly selected escalation
        # ---------------------------------------------------------
        action = decision.action

        if action is RecoveryAction.ESCALATE:
            policy_evidence["reason"] = "agent_selected_escalation"

            return {
                "selected_action": action.value,
                "outcome": "Escalated for human review",
                "execution_evidence": {
                    "policy": policy_evidence,
                    "action": {
                        "selected": action.value,
                    },
                },
            }

        # ---------------------------------------------------------
        # 4. Prepare deterministic tool invocation
        # ---------------------------------------------------------
        payment_id = context["payment"]["id"]
        tool_name = action.value
        tool_input: dict[str, Any] = {}

        try:
            idempotency_key = (
                f"subscription-recovery:"
                f"{payment_id}:"
                f"{action.value}"
            )

            if action is RecoveryAction.RETRY_PAYMENT:
                tool_input = {
                    "payment_id": payment_id,
                    "idempotency_key": idempotency_key,
                }

            elif action is RecoveryAction.CREATE_PAYMENT_LINK:
                tool_input = {
                    "payment_id": payment_id,
                    "idempotency_key": idempotency_key,
                }

            elif action is RecoveryAction.SEND_MESSAGE:
                tool_input = {
                    "customer_id": context["customer"]["id"],
                    "message": state.get(
                        "user_request",
                        "Payment recovery requires attention.",
                    ),
                    "idempotency_key": idempotency_key,
                }

            elif action is RecoveryAction.ISSUE_REFUND:
                if context["payment"]["status"] not in {
                    PaymentStatus.CAPTURED,
                    PaymentStatus.PARTIALLY_REFUNDED,
                }:
                    raise services.InvalidOperationError(
                        "Payment is not refundable"
                    )

                tool_input = {
                    "payment_id": payment_id,
                    "amount": context["payment"]["amount"],
                    "idempotency_key": idempotency_key,
                }

            else:
                raise services.InvalidOperationError(
                    "Unsupported recovery action"
                )

            # -----------------------------------------------------
            # 5. Capture authoritative state BEFORE execution
            # -----------------------------------------------------
            before_payment = services.get_payment(
                self._session,
                payment_id,
            )

            before_state = {
                "payment_id": str(before_payment.id),
                "status": before_payment.status.value,
                "amount": str(before_payment.amount),
                "currency": before_payment.currency,
            }

            # -----------------------------------------------------
            # 6. Execute actual deterministic tool
            # -----------------------------------------------------
            tool = self._tools[tool_name]
            result = tool.invoke(tool_input)

            # -----------------------------------------------------
            # 7. Reconstruct authoritative state change
            # -----------------------------------------------------
            state_change: dict[str, Any]

            if action is RecoveryAction.RETRY_PAYMENT:
                # retry_payment creates a NEW payment rather than
                # mutating the original payment.
                retry_payment_id = result["id"]

                retry_payment = services.get_payment(
                    self._session,
                    retry_payment_id,
                )

                state_change = {
                    "entity": "payment",
                    "operation": "created_from_retry",
                    "before": before_state,
                    "after": {
                        "payment_id": str(retry_payment.id),
                        "status": retry_payment.status.value,
                        "amount": str(retry_payment.amount),
                        "currency": retry_payment.currency,
                        "retry_of_payment_id": str(before_payment.id),
                    },
                }

            elif action is RecoveryAction.ISSUE_REFUND:
                # issue_refund mutates the existing payment status.
                after_payment = services.get_payment(
                    self._session,
                    payment_id,
                )

                state_change = {
                    "entity": "payment",
                    "operation": "updated",
                    "before": before_state,
                    "after": {
                        "payment_id": str(after_payment.id),
                        "status": after_payment.status.value,
                        "amount": str(after_payment.amount),
                        "currency": after_payment.currency,
                    },
                }

            elif action is RecoveryAction.CREATE_PAYMENT_LINK:
                state_change = {
                    "entity": "payment_link",
                    "operation": "created",
                    "before": None,
                    "after": {
                        "id": str(result["id"]),
                        "payment_id": (
                            str(result["payment_id"])
                            if result.get("payment_id") is not None
                            else None
                        ),
                        "customer_id": (
                            str(result["customer_id"])
                            if result.get("customer_id") is not None
                            else None
                        ),
                        "status": result.get("status"),
                        "amount": str(result["amount"]),
                        "currency": result["currency"],
                    },
                }

            elif action is RecoveryAction.SEND_MESSAGE:
                state_change = {
                    "entity": "communication",
                    "operation": "created",
                    "before": None,
                    "after": {
                        "id": str(result["id"]),
                        "customer_id": str(result["customer_id"]),
                        "channel": result["channel"],
                        "status": result["status"],
                    },
                }

            else:
                state_change = {
                    "entity": "none",
                    "operation": "none",
                    "before": None,
                    "after": None,
                }

        except (services.DomainError, ToolException) as error:
            return {
                "selected_action": action.value,
                "outcome": f"Action rejected: {error}",
                "errors": [str(error)],
                "execution_evidence": {
                    "policy": _json_safe(policy_evidence),
                    "action": {
                        "selected": action.value,
                    },
                    "tool": {
                        "name": tool_name,
                        "input": _json_safe(tool_input),
                        "status": "rejected",
                        "error": str(error),
                    },
                },
            }

        # ---------------------------------------------------------
        # 8. Successful forensic evidence
        # ---------------------------------------------------------
        execution_evidence = {
            "policy": _json_safe(policy_evidence),
            "action": {
                "selected": action.value,
            },
            "tool": {
                "name": tool_name,
                "input": _json_safe(tool_input),
                "status": "executed",
                "result": _json_safe(result),
            },
            "state_change": _json_safe(state_change),
        }

        return {
            "selected_action": action.value,
            "outcome": "Action executed",
            "action_result": result,
            "execution_evidence": execution_evidence,
        }