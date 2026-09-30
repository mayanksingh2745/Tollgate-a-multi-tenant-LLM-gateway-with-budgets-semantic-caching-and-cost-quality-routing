"""DisabledRouter — passthrough that preserves existing behavior."""

from gateway.src.router.decision import RoutingDecision
from gateway.src.schemas.chat import ChatCompletionRequest


class DisabledRouter:
    """
    Router that performs no routing.
    Returns the original model specified by the client, preserving pre-Phase 9 behavior.
    """

    async def route(self, request: ChatCompletionRequest) -> RoutingDecision:
        return RoutingDecision(
            selected_model=request.model,
            route="passthrough",
            confidence=0.0,
            reason="router_disabled",
            original_model=request.model,
        )
