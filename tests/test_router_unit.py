"""Unit tests for Learned Model Router components."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock

import pytest
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
    extract_features,
)
from gateway.src.router.learned import LearnedRouter
from gateway.src.router.metrics import RouterMetrics
from gateway.src.router.static import StaticRouter
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage


def test_feature_names_and_count():
    assert len(FEATURE_NAMES) == 15
    assert "token_count_estimate" in FEATURE_NAMES
    assert "has_code_block" in FEATURE_NAMES
    assert "has_sql_keywords" in FEATURE_NAMES
    assert "has_math_symbols" in FEATURE_NAMES


def test_feature_extraction_simple_query():
    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Hello, what time is it?")],
    )
    features = extract_features(req)
    assert features.schema_version == FEATURE_SCHEMA_VERSION
    vals = features.to_list()
    assert len(vals) == 15

    # Simple prompt should have no code, sql, math
    feat_dict = dict(zip(FEATURE_NAMES, vals, strict=True))
    assert feat_dict["message_count"] == 1.0
    assert feat_dict["user_turn_count"] == 1.0
    assert feat_dict["system_message_count"] == 0.0
    assert feat_dict["has_code_block"] == 0.0
    assert feat_dict["has_sql_keywords"] == 0.0
    assert feat_dict["has_math_symbols"] == 0.0
    assert feat_dict["question_mark_count"] == 1.0


def test_feature_extraction_complex_code_and_sql():
    content = (
        "Here is the database schema:\n"
        "```sql\n"
        "SELECT id, name FROM users WHERE active = true ORDER BY id DESC;\n"
        "```\n"
        "Also calculate 42 * 10 = ?"
    )
    req = ChatCompletionRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="system", content="You are a senior DB engineer."),
            ChatMessage(role="user", content=content),
        ],
    )
    features = extract_features(req)
    feat_dict = dict(zip(FEATURE_NAMES, features.to_list(), strict=True))
    assert feat_dict["message_count"] == 2.0
    assert feat_dict["system_message_count"] == 1.0
    assert feat_dict["user_turn_count"] == 1.0
    assert feat_dict["has_code_block"] == 1.0
    assert feat_dict["has_sql_keywords"] == 1.0
    assert feat_dict["has_math_symbols"] == 1.0


def test_feature_extraction_multimodal_list_content():
    req = ChatCompletionRequest(
        model="mock-model",
        messages=[
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "Can you see this?"},
                    {"type": "image_url", "image_url": {"url": "http://example.com/img.png"}},
                ],
            )
        ],
    )
    features = extract_features(req)
    feat_dict = dict(zip(FEATURE_NAMES, features.to_list(), strict=True))
    assert feat_dict["char_count"] == len("Can you see this?")
    assert feat_dict["has_url"] == 0.0  # URL was in image dict, not in extracted text


def test_routing_decision_dataclass():
    d = RoutingDecision(
        selected_model="mock-fast",
        route="cheap",
        confidence=0.85,
        reason="high_confidence",
        original_model="mock-model",
    )
    assert d.selected_model == "mock-fast"
    assert d.route == "cheap"
    assert d.confidence == 0.85
    assert d.policy_version == ROUTER_POLICY_VERSION
    assert not d.shadow
    assert not d.fallback

    # Immutability
    with pytest.raises(FrozenInstanceError):
        d.selected_model = "other"  # type: ignore


@pytest.mark.asyncio
async def test_disabled_router():
    router = DisabledRouter()
    req = ChatCompletionRequest(
        model="my-custom-model", messages=[ChatMessage(role="user", content="Hi")]
    )
    decision = await router.route(req)
    assert decision.selected_model == "my-custom-model"
    assert decision.route == "passthrough"
    assert decision.reason == "router_disabled"
    assert decision.confidence == 0.0


@pytest.mark.asyncio
async def test_static_router():
    router = StaticRouter(model="mock-fast", route_name="static_fast")
    req = ChatCompletionRequest(
        model="original-strong", messages=[ChatMessage(role="user", content="Hi")]
    )
    decision = await router.route(req)
    assert decision.selected_model == "mock-fast"
    assert decision.route == "static_fast"
    assert decision.original_model == "original-strong"
    assert decision.confidence == 1.0


def test_router_metrics():
    metrics = RouterMetrics()
    metrics.record_request("cheap", confidence=0.88)
    metrics.record_request("strong", confidence=0.32)
    metrics.record_request("passthrough")
    metrics.record_request("cheap", confidence=0.95, shadow=True)
    metrics.record_fallback()
    metrics.record_inference_error()
    metrics.record_feature_extraction_latency(0.002)
    metrics.record_inference_latency(0.005)

    summary = metrics.get_summary()
    assert summary["requests_total"] == 4
    assert summary["cheap_selected_total"] == 2
    assert summary["strong_selected_total"] == 1
    assert summary["passthrough_total"] == 1
    assert summary["shadow_decisions_total"] == 1
    assert summary["fallback_total"] == 1
    assert summary["inference_errors_total"] == 1
    assert summary["avg_feature_extraction_ms"] > 0
    assert summary["avg_inference_ms"] > 0


def test_artifact_validation_missing_dir(tmp_path: Path):
    non_existent = tmp_path / "does_not_exist"
    artifact = RouterArtifact(str(non_existent))
    with pytest.raises(ArtifactValidationError, match="directory not found"):
        artifact.load()


def test_artifact_validation_missing_files(tmp_path: Path):
    model_dir = tmp_path / "model_dir"
    model_dir.mkdir()
    artifact = RouterArtifact(str(model_dir))
    with pytest.raises(ArtifactValidationError, match="Model file not found"):
        artifact.load()


def test_artifact_validation_schema_mismatch(tmp_path: Path):
    model_dir = tmp_path / "model_dir"
    model_dir.mkdir()
    (model_dir / "model.joblib").write_text("dummy")
    metadata = {
        "model_version": "v1.0.0",
        "feature_schema_version": 999,  # Mismatch!
        "cheap_model": "mock-fast",
        "strong_model": "mock-model",
        "threshold": 0.5,
    }
    (model_dir / "metadata.json").write_text(json.dumps(metadata))

    artifact = RouterArtifact(str(model_dir))
    with pytest.raises(ArtifactValidationError, match="Feature schema mismatch"):
        artifact.load()


def test_artifact_validation_version_mismatch(tmp_path: Path):
    model_dir = tmp_path / "model_dir"
    model_dir.mkdir()
    (model_dir / "model.joblib").write_text("dummy")
    metadata = {
        "model_version": "v1.0.0",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "cheap_model": "mock-fast",
        "strong_model": "mock-model",
        "threshold": 0.5,
    }
    (model_dir / "metadata.json").write_text(json.dumps(metadata))

    artifact = RouterArtifact(str(model_dir))
    with pytest.raises(ArtifactValidationError, match="Model version mismatch"):
        artifact.load(expected_version="v2.0.0")


@pytest.mark.asyncio
async def test_learned_router_routing():
    # Mock artifact and classifier
    mock_artifact = MagicMock(spec=RouterArtifact)
    mock_artifact.is_loaded = True
    mock_artifact.metadata = ArtifactMetadata(
        model_version="v1.0.0",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        training_timestamp="2026-09-30T00:00:00Z",
        dataset_version="1.0.0",
        cheap_model="mock-fast",
        strong_model="mock-model",
        threshold=0.6,
        training_config={},
        evaluation_metrics={},
        calibration={},
    )

    mock_model = MagicMock()
    # Return high confidence for cheap
    mock_model.predict_proba.return_value = [[0.1, 0.9]]
    mock_artifact.model = mock_model

    router = LearnedRouter(
        artifact=mock_artifact,
        cheap_model="mock-fast",
        strong_model="mock-model",
        threshold=0.6,
    )

    req = ChatCompletionRequest(
        model="mock-model", messages=[ChatMessage(role="user", content="Hello")]
    )
    decision = await router.route(req)

    assert decision.selected_model == "mock-fast"
    assert decision.route == "cheap"
    assert decision.confidence == 0.9
    assert not decision.fallback

    # Now simulate low confidence -> strong model
    mock_model.predict_proba.return_value = [[0.7, 0.3]]
    decision_strong = await router.route(req)
    assert decision_strong.selected_model == "mock-model"
    assert decision_strong.route == "strong"
    assert decision_strong.confidence == 0.3


@pytest.mark.asyncio
async def test_learned_router_fail_open_on_error():
    mock_artifact = MagicMock(spec=RouterArtifact)
    mock_artifact.is_loaded = True
    mock_artifact.metadata = None
    mock_model = MagicMock()
    mock_model.predict_proba.side_effect = RuntimeError("Inference explosion")
    mock_artifact.model = mock_model

    router = LearnedRouter(
        artifact=mock_artifact,
        cheap_model="mock-fast",
        strong_model="mock-model",
        fallback_model="mock-fallback",
    )

    req = ChatCompletionRequest(
        model="original-model", messages=[ChatMessage(role="user", content="Hello")]
    )
    decision = await router.route(req)

    assert decision.selected_model == "mock-fallback"
    assert decision.route == "fallback"
    assert decision.fallback is True
    assert "inference_error" in decision.reason


def test_cost_provider():
    cost_provider = ModelCostProvider()
    cost_cheap = cost_provider.calculate_cost("mock-fast", input_tokens=1000, output_tokens=500)
    cost_strong = cost_provider.calculate_cost("mock-model", input_tokens=1000, output_tokens=500)

    # Cheap model should be significantly cheaper than strong model
    assert cost_cheap < cost_strong
    assert cost_cheap > 0
