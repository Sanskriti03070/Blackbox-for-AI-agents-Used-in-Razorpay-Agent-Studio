from __future__ import annotations

from typing import Any


def _event_map(events: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}

    for event in events:
        grouped.setdefault(event.event_type, []).append(event)

    return grouped


def _evidence(event: Any) -> dict[str, Any]:
    return {
        "event_id": event.id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat(),
    }


def _first(events: dict[str, list[Any]], event_type: str) -> Any | None:
    items = events.get(event_type, [])
    return items[0] if items else None


def build_investigation(run: Any, events: list[Any]) -> dict[str, Any]:
    """
    Reconstruct business-level intelligence from an agent trace.

    This layer is deterministic: every conclusion must be grounded in
    persisted trace evidence.
    """
    grouped = _event_map(events)

    decision_event = _first(grouped, "decision_generated")
    policy_event = _first(grouped, "policy_checked")
    tool_event = _first(grouped, "tool_executed")
    state_event = _first(grouped, "state_changed")
    completed_event = _first(grouped, "agent_completed")
    failed_event = _first(grouped, "agent_failed")
    action_rejected_event = _first(grouped, "action_rejected")

    decision = None
    if decision_event and decision_event.result:
        decision = {
            **decision_event.result,
            "evidence": _evidence(decision_event),
        }

    policy = None
    if policy_event and policy_event.result:
        policy = {
            **policy_event.result,
            "evidence": _evidence(policy_event),
        }

    tool = None
    if tool_event:
        tool = {
            "name": (tool_event.payload or {}).get("name"),
            "input": (tool_event.payload or {}).get("input"),
            **(tool_event.result or {}),
            "evidence": _evidence(tool_event),
        }

    state_changes: list[dict[str, Any]] = []
    for event in grouped.get("state_changed", []):
        state_changes.append(
            {
                **(event.result or {}),
                "entity": (event.payload or {}).get("entity"),
                "operation": (event.payload or {}).get("operation"),
                "evidence": _evidence(event),
            }
        )

    integrity_issues: list[dict[str, Any]] = []
    evidence = [_evidence(event) for event in events]

    # Verify that the tool's payment_id agrees with the agent context.
    context_payment_id = None
    started_event = _first(grouped, "agent_started")

    if started_event and started_event.payload:
        context_payment_id = started_event.payload.get("payment_id")

    tool_payment_id = None
    if tool_event and tool_event.payload:
        tool_input = tool_event.payload.get("input") or {}
        tool_payment_id = tool_input.get("payment_id")

    if context_payment_id and tool_payment_id:
        if str(context_payment_id) != str(tool_payment_id):
            integrity_issues.append(
                {
                    "severity": "warning",
                    "type": "context_action_mismatch",
                    "message": (
                        "The payment referenced by the agent context does not "
                        "match the payment used by the tool execution."
                    ),
                    "context_payment_id": context_payment_id,
                    "tool_payment_id": tool_payment_id,
                    "evidence": [
                        _evidence(started_event),
                        _evidence(tool_event),
                    ],
                }
            )

    if failed_event:
        conclusion = (
            failed_event.result or {}
        ).get(
            "outcome",
            "The agent failed before completing the requested action.",
        )
    elif action_rejected_event:
        conclusion = (
            action_rejected_event.result or {}
        ).get(
            "outcome",
            "The selected action was rejected.",
        )
    elif completed_event:
        outcome = (completed_event.result or {}).get("outcome")

        if outcome == "Action executed":
            conclusion = (
                f"The agent selected "
                f"{(run.selected_action or 'an action')} and the action executed successfully."
            )
        else:
            conclusion = outcome or "The agent completed without a recorded outcome."
    else:
        conclusion = run.outcome or "The investigation has no terminal event."

        evidence = [_evidence(event) for event in events]

    return {
        "run": {
            "run_id": run.run_id,
            "agent_name": run.agent_name,
            "agent_version": run.agent_version,
            "merchant_id": run.merchant_id,
            "customer_id": run.customer_id,
            "subscription_id": run.subscription_id,
            "payment_id": run.payment_id,
            "user_request": run.user_request,
            "status": run.status,
            "selected_action": run.selected_action,
            "confidence": run.confidence,
            "outcome": run.outcome,
            "started_at": run.started_at.isoformat(),
            "completed_at": (
                run.completed_at.isoformat()
                if run.completed_at
                else None
            ),
            "error_summary": run.error_summary,
        },

        "incident": {
            "status": run.status,
            "agent": run.agent_name,
            "request": run.user_request,
            "payment_id": run.payment_id,
        },

        "timeline": {
            "decision": decision,
            "policy": policy,
            "tool": tool,
            "state_changes": state_changes,
            "event_count": len(events),
        },

        "conclusion": conclusion,

        "evidence_integrity": {
            "status": "issues_found" if integrity_issues else "clean",
            "issues": integrity_issues,
        },

        "evidence": evidence,
    }
