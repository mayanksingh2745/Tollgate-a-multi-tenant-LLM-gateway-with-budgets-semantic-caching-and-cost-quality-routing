"""ModelRouterService — manages router lifecycle and gateway request routing."""

import logging
from typing import Any, Optional

from gateway.src.router.artifact import ArtifactValidationError, RouterArtifact
from gateway.src.router.decision import RoutingDecision
from gateway.src.router.disabled import DisabledRouter
from gateway.src.router.learned import LearnedRouter
from gateway.src.router.metrics import router_metrics
from gateway.src.router.static import StaticRouter
from gateway.src.schemas.chat import ChatCompletionRequest
from tollgate_core.config import Settings, get_settings

logger = logging.getLogger("tollgate.router.service")


class ModelRouterService:
    """
    Central service for model routing in Tollgate.
    Dispatches to DisabledRouter, StaticRouter, or LearnedRouter based on settings.
    Ensures safe fail-open behavior so router failures never crash gateway requests.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self._settings = settings or get_settings()
        self._router: Any = None
        self._artifact: Optional[RouterArtifact] = None
        self.initialize()

    def initialize(self) -> None:
        """Initialize the router implementation according to current settings."""
        if not self._settings.router_enabled or self._settings.router_mode == "disabled":
            logger.info("Model router is disabled (passthrough).")
            self._router = DisabledRouter()
            self._artifact = None
            return

        if self._settings.router_mode == "static":
            logger.info(
                f"Model router configured in static mode: "
                f"target={self._settings.router_strong_model}"
            )
            self._router = StaticRouter(model=self._settings.router_strong_model)
            self._artifact = None
            return

        if self._settings.router_mode == "learned":
            logger.info(
                f"Initializing LearnedRouter with artifact path: "
                f"{self._settings.router_artifact_path}"
            )
            self._artifact = RouterArtifact(self._settings.router_artifact_path)
            try:
                self._artifact.load(expected_version=self._settings.router_model_version)
                self._router = LearnedRouter(
                    artifact=self._artifact,
                    cheap_model=self._settings.router_cheap_model,
                    strong_model=self._settings.router_strong_model,
                    threshold=self._settings.router_quality_threshold,
                    fallback_model=self._settings.router_fallback_model,
                    shadow_mode=self._settings.router_shadow_mode,
                )
                logger.info("LearnedRouter initialized successfully.")
            except ArtifactValidationError as e:
                logger.warning(
                    f"Failed to load router artifact ({e}). Failing open with DisabledRouter."
                )
                self._router = DisabledRouter()
            except Exception as e:
                logger.error(
                    f"Unexpected error initializing LearnedRouter: {e}. Failing open.",
                    exc_info=True,
                )
                self._router = DisabledRouter()
            return

        logger.warning(
            f"Unknown router mode '{self._settings.router_mode}'. Defaulting to DisabledRouter."
        )
        self._router = DisabledRouter()
        self._artifact = None

    def set_router(self, router: Any) -> None:
        """Explicitly set the router implementation (e.g. for testing)."""
        self._router = router

    def reconfigure(self, settings: Settings) -> None:
        """Reconfigure router service with new settings."""
        self._settings = settings
        self.initialize()

    @property
    def active_router(self) -> Any:
        return self._router

    @property
    def artifact(self) -> Optional[RouterArtifact]:
        return self._artifact

    async def route(self, request: ChatCompletionRequest) -> RoutingDecision:
        """
        Evaluate request and return a RoutingDecision.

        Guaranteed not to raise an unhandled exception.
        """
        try:
            return await self._router.route(request)
        except Exception as e:
            logger.error(f"Unhandled error in router: {e}. Failing open.", exc_info=True)
            router_metrics.record_inference_error()
            router_metrics.record_fallback()
            fallback_target = self._settings.router_fallback_model or request.model
            return RoutingDecision(
                selected_model=fallback_target,
                route="fallback",
                confidence=0.0,
                reason=f"unhandled_router_error: {e}",
                fallback=True,
                original_model=request.model,
            )


# Global singleton instance
model_router = ModelRouterService()
