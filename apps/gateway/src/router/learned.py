"""LearnedRouter — classifier-based routing between cheap and strong models."""

import logging
import math
import time
from typing import Optional

from gateway.src.router.artifact import RouterArtifact
from gateway.src.router.decision import ROUTER_POLICY_VERSION, RoutingDecision
from gateway.src.router.features import FEATURE_SCHEMA_VERSION, extract_features
from gateway.src.router.metrics import router_metrics
from gateway.src.schemas.chat import ChatCompletionRequest

logger = logging.getLogger("tollgate.router.learned")


class LearnedRouter:
    """
    Routes requests to a cheaper or stronger model using a trained ML classifier.

    If confidence >= quality_threshold: routes to cheap_model.
    Otherwise: routes to strong_model.

    On any error during feature extraction or inference, fails open to fallback_model
    (or the request's original model).
    """

    def __init__(
        self,
        artifact: RouterArtifact,
        cheap_model: str,
        strong_model: str,
        threshold: float = 0.5,
        fallback_model: Optional[str] = None,
        shadow_mode: bool = False,
    ):
        self._artifact = artifact
        self._cheap_model = cheap_model
        self._strong_model = strong_model
        self._threshold = threshold
        self._fallback_model = fallback_model
        self._shadow_mode = shadow_mode

    @property
    def cheap_model(self) -> str:
        return self._cheap_model

    @property
    def strong_model(self) -> str:
        return self._strong_model

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def shadow_mode(self) -> bool:
        return self._shadow_mode

    async def route(self, request: ChatCompletionRequest) -> RoutingDecision:
        original_model = request.model
        fallback_target = self._fallback_model or original_model

        if not self._artifact.is_loaded or self._artifact.model is None:
            logger.warning("Router artifact is not loaded; failing open.")
            router_metrics.record_fallback()
            router_metrics.record_request("fallback", shadow=self._shadow_mode)
            return RoutingDecision(
                selected_model=fallback_target,
                route="fallback",
                confidence=0.0,
                reason="artifact_not_loaded",
                fallback=True,
                shadow=self._shadow_mode,
                original_model=original_model,
            )

        # 1. Feature extraction
        t0 = time.perf_counter()
        try:
            features = extract_features(request)
            fe_time = time.perf_counter() - t0
            router_metrics.record_feature_extraction_latency(fe_time)
        except Exception as e:
            logger.error(f"Router feature extraction error: {e}", exc_info=True)
            router_metrics.record_inference_error()
            router_metrics.record_fallback()
            router_metrics.record_request("fallback", shadow=self._shadow_mode)
            return RoutingDecision(
                selected_model=fallback_target,
                route="fallback",
                confidence=0.0,
                reason=f"feature_extraction_error: {e}",
                fallback=True,
                shadow=self._shadow_mode,
                original_model=original_model,
            )

        # 2. Classifier inference
        t1 = time.perf_counter()
        try:
            model = self._artifact.model
            X = [features.to_list()]

            if hasattr(model, "predict_proba"):
                probs = model.predict_proba(X)
                if hasattr(probs, "shape"):
                    confidence = float(probs[0][1]) if probs.shape[1] >= 2 else float(probs[0][0])
                else:
                    confidence = float(probs[0][1]) if len(probs[0]) >= 2 else float(probs[0][0])
            elif hasattr(model, "decision_function"):
                df = model.decision_function(X)
                confidence = 1.0 / (1.0 + math.exp(-float(df[0])))
            else:
                pred = model.predict(X)
                confidence = 1.0 if pred[0] == 1 else 0.0

            inf_time = time.perf_counter() - t1
            router_metrics.record_inference_latency(inf_time)
        except Exception as e:
            logger.error(f"Router inference error: {e}", exc_info=True)
            router_metrics.record_inference_error()
            router_metrics.record_fallback()
            router_metrics.record_request("fallback", shadow=self._shadow_mode)
            return RoutingDecision(
                selected_model=fallback_target,
                route="fallback",
                confidence=0.0,
                reason=f"inference_error: {e}",
                fallback=True,
                shadow=self._shadow_mode,
                original_model=original_model,
            )

        # 3. Decision rule
        model_version = (
            self._artifact.metadata.model_version if self._artifact.metadata else "unknown"
        )
        schema_version = (
            self._artifact.metadata.feature_schema_version
            if self._artifact.metadata
            else FEATURE_SCHEMA_VERSION
        )

        if confidence >= self._threshold:
            selected_model = self._cheap_model
            route = "cheap"
            reason = f"confidence_{confidence:.3f}_gte_threshold_{self._threshold:.3f}"
        else:
            selected_model = self._strong_model
            route = "strong"
            reason = f"confidence_{confidence:.3f}_lt_threshold_{self._threshold:.3f}"

        router_metrics.record_request(route, confidence, shadow=self._shadow_mode)

        return RoutingDecision(
            selected_model=selected_model,
            route=route,
            confidence=confidence,
            reason=reason,
            policy_version=ROUTER_POLICY_VERSION,
            model_version=model_version,
            feature_schema_version=schema_version,
            shadow=self._shadow_mode,
            fallback=False,
            original_model=original_model,
        )
