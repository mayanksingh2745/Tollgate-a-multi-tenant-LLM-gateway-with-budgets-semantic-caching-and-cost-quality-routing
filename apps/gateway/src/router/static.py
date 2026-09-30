"""StaticRouter — always routes to a configured model."""

from gateway.src.router.decision import RoutingDecision
from gateway.src.schemas.chat import ChatCompletionRequest


class StaticRouter:
    """
    Router that always selects a static configured model.
    Useful for debugging, A/B testing, and baseline comparison.
    """

    def __init__(self, model: str, route_name: str = "static"):
        self._model = model
        self._route_name = route_name

    async def route(self, request: ChatCompletionRequest) -> RoutingDecision:
        return RoutingDecision(
            selected_model=self._model,
            route=self._route_name,
            confidence=1.0,
            reason=f"static_route_to_{self._model}",
            original_model=request.model,
        )
