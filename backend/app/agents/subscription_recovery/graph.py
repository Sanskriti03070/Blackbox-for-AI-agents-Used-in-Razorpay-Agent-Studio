from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.subscription_recovery.decision import DecisionModel, StructuredDecision
from app.agents.subscription_recovery.executor import ActionExecutor
from app.agents.subscription_recovery.state import SubscriptionRecoveryState


def reasoning_node(state: SubscriptionRecoveryState, model: DecisionModel | None = None) -> dict[str, Any]:
    """Generate one schema-validated decision without executing any action."""
    context = state.get("context")
    if context is None:
        return {"errors": ["Payment context is required before reasoning"],
        "outcome": "No action executed: payment context is missing",}
    if model is None:
        return {"errors": ["Decision model is not configured"], "outcome": "No action executed: decision model is unavailable"}
    try:
        decision = StructuredDecision.model_validate(model.decide(state.get("user_request", ""), context))
    except Exception as error:
        return {"errors": [f"Decision model failed: {error}"], "outcome": "No action executed: decision generation failed"}
    return {"decision": decision, "decision_reason": decision.reason, "confidence": decision.confidence}


def build_subscription_recovery_graph(
    model: DecisionModel | None = None,
    action_executor: ActionExecutor | None = None,
) -> CompiledStateGraph:
    """Compile the reasoning and deterministic action stages."""
    graph = StateGraph(SubscriptionRecoveryState)
    graph.add_node("reasoning", lambda state: reasoning_node(state, model))
    graph.add_node("execute_action", lambda state: execute_action_node(state, action_executor))
    graph.add_edge(START, "reasoning")
    graph.add_edge("reasoning", "execute_action")
    graph.add_edge("execute_action", END)
    return graph.compile()


def execute_action_node(
    state: SubscriptionRecoveryState,
    action_executor: ActionExecutor | None = None,
) -> dict[str, Any]:
    decision = state.get("decision")

    if decision is None:
        return {}

    if action_executor is None:
        return {
            "outcome": "No action executed: action executor is unavailable"
        }

    execution_result = action_executor.execute(decision, state)

    return {
        "selected_action": execution_result.get("selected_action"),
        "decision_reason": execution_result.get("decision_reason"),
        "outcome": execution_result.get("outcome"),
        "action_result": execution_result.get("action_result"),
        "execution_evidence": execution_result.get("execution_evidence"),
        "errors": execution_result.get("errors", []),
    }