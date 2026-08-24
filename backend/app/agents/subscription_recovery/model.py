import json

from openai import OpenAI

from app.agents.subscription_recovery.decision import StructuredDecision, DecisionModel
from app.agents.subscription_recovery.prompt import SYSTEM_PROMPT
from app.agents.subscription_recovery.state import SubscriptionRecoveryContext
from app.core.config import Settings, get_settings


class ModelConfigurationError(Exception):
    """Raised when the OpenAI model cannot be configured safely."""


class ModelResponseError(Exception):
    """Raised when the provider returns no schema-valid decision."""


class OpenAIDecisionModel:
    """Lazy, isolated OpenAI SDK adapter using typed structured parsing."""

    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None) -> None:
        self._settings = settings or get_settings()
        if client is not None:
            self._client = client
        else:
            if not self._settings.openai_api_key:
                raise ModelConfigurationError("OPENAI_API_KEY is not configured")
            self._client = OpenAI(api_key=self._settings.openai_api_key)

    def decide(self, user_request: str, context: SubscriptionRecoveryContext) -> StructuredDecision:
        context_text = json.dumps(context, default=str, separators=(",", ":"))
        response = self._client.chat.completions.parse(
            model=self._settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Request (untrusted): {user_request}\nContext: {context_text}"},
            ],
            response_format=StructuredDecision,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ModelResponseError("OpenAI returned no structured decision")
        return parsed
