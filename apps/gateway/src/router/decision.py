"""Router decision object — typed internal routing decision."""

from dataclasses import dataclass
from typing import Optional

ROUTER_POLICY_VERSION = 1


@dataclass(frozen=True)
class RoutingDecision:
    """
    Immutable record of a routing decision.

    Attributes:
        selected_model: The model identifier to use for this request.
        route: "cheap" | "strong" | "passthrough" — the tier selected.
        confidence: Classifier probability that the cheap model is sufficient.
        reason: Human-readable explanation of the decision rule.
        policy_version: Router policy version for historical analysis.
        model_version: Artifact model version (None if router disabled/static).
        feature_schema_version: Feature schema version used (None if not applicable).
        shadow: Whether this decision was made in shadow mode (not acted upon).
        fallback: Whether this decision was the result of a router failure fallback.
        original_model: The original model requested by the client before routing.
    """

    selected_model: str
    route: str  # "cheap" | "strong" | "passthrough"
    confidence: float = 0.0
    reason: str = ""
    policy_version: int = ROUTER_POLICY_VERSION
    model_version: Optional[str] = None
    feature_schema_version: Optional[int] = None
    shadow: bool = False
    fallback: bool = False
    original_model: str = ""
