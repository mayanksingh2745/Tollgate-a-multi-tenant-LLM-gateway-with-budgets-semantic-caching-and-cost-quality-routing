"""Tests for the router benchmark generation, training, and evaluation pipeline."""

import json
from pathlib import Path

from gateway.src.router.features import FEATURE_SCHEMA_VERSION

from evaluation.router.evaluate import run_evaluation
from evaluation.router.generate import generate_benchmark_dataset
from evaluation.router.metrics import compute_router_metrics
from evaluation.router.predict import predict_route
from evaluation.router.train import train_and_export


def test_benchmark_dataset_generation():
    dataset = generate_benchmark_dataset(num_samples=20, seed=42)
    assert len(dataset) == 20

    # Half cheap, half strong
    cheap_count = sum(1 for d in dataset if d["cheap_sufficient"] == 1)
    strong_count = sum(1 for d in dataset if d["cheap_sufficient"] == 0)
    assert cheap_count == 10
    assert strong_count == 10

    sample = dataset[0]
    assert "id" in sample
    assert "messages" in sample
    assert "cheap_sufficient" in sample
    assert "quality_cheap" in sample
    assert "quality_strong" in sample


def test_metrics_calculation_ideal():
    y_true = [1, 1, 0, 0]
    y_pred = [1, 1, 0, 0]
    y_probs = [0.95, 0.88, 0.12, 0.05]

    m = compute_router_metrics(y_true, y_pred, y_probs, threshold=0.5)
    assert m.accuracy == 1.0
    assert m.precision == 1.0
    assert m.recall == 1.0
    assert m.f1_score == 1.0
    assert m.false_positive_rate == 0.0
    assert m.false_negative_rate == 0.0
    assert m.brier_score < 0.02
    assert m.estimated_quality_degradation_pct == 0.0


def test_metrics_calculation_always_cheap():
    y_true = [1, 1, 0, 0]
    y_pred = [1, 1, 1, 1]
    y_probs = [1.0, 1.0, 1.0, 1.0]

    m = compute_router_metrics(y_true, y_pred, y_probs, threshold=0.5)
    assert m.accuracy == 0.5
    assert m.precision == 0.5
    assert m.recall == 1.0
    assert m.false_positive_rate == 1.0  # All negative samples are false positives!
    assert m.false_negative_rate == 0.0
    assert m.estimated_quality_degradation_pct == 50.0  # 2 out of 4 corrupted


def test_train_and_export_pipeline(tmp_path: Path):
    dataset_path = tmp_path / "test_benchmark.json"
    artifact_dir = tmp_path / "artifacts"

    # Write small dataset
    samples = generate_benchmark_dataset(num_samples=40, seed=42)
    with open(dataset_path, "w", encoding="utf-8") as f:
        json.dump(samples, f)

    metadata = train_and_export(
        dataset_path=dataset_path,
        artifact_dir=artifact_dir,
        model_version="test-v1",
        dataset_version="test-1.0",
    )

    assert metadata["model_version"] == "test-v1"
    assert metadata["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert (artifact_dir / "model.joblib").exists()
    assert (artifact_dir / "metadata.json").exists()


def test_evaluation_runner(tmp_path: Path):
    output_report = tmp_path / "report.json"
    report = run_evaluation(output_path=output_report)

    assert output_report.exists()
    assert "baselines" in report
    assert "threshold_sweep" in report
    assert len(report["threshold_sweep"]) >= 5

    # Check baseline relationship: Always Strong vs Learned
    strong_b = report["baselines"]["always_strong"]
    learned_b = report["baselines"]["learned_router_threshold_0_7"]

    # Learned router should provide cost savings with minimal FPR
    assert learned_b["estimated_cost_savings_pct"] > strong_b["estimated_cost_savings_pct"]
    assert learned_b["false_positive_rate"] <= 0.05


def test_predict_route_utility():
    res_simple = predict_route("Hello, what is the weather like?")
    assert res_simple["route"] in ("cheap", "strong")
    assert "confidence" in res_simple
    assert "features" in res_simple
    assert len(res_simple["features"]) == 15
