"""Learned Model Router module for Tollgate."""

from gateway.src.router.artifact import (
    ArtifactMetadata,
    ArtifactValidationError,
    RouterArtifact,
)
from gateway.src.router.cost import ModelCostProvider
from gateway.src.router.decision import ROUTER_POLICY_VERSION, RoutingDecision
from gateway.src.router.disabled import DisabledRouter
from gateway.src.router.features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    RequestFeatures,
    extract_features,
)
from gateway.src.router.learned import LearnedRouter
from gateway.src.router.metrics import RouterMetrics, router_metrics
from gateway.src.router.service import ModelRouterService, model_router
from gateway.src.router.static import StaticRouter

__all__ = [
    "ArtifactMetadata",
    "ArtifactValidationError",
    "DisabledRouter",
    "FEATURE_NAMES",
    "FEATURE_SCHEMA_VERSION",
    "LearnedRouter",
    "ModelCostProvider",
    "ModelRouterService",
    "RequestFeatures",
    "ROUTER_POLICY_VERSION",
    "RouterArtifact",
    "RouterMetrics",
    "RoutingDecision",
    "StaticRouter",
    "extract_features",
    "model_router",
    "router_metrics",
]
