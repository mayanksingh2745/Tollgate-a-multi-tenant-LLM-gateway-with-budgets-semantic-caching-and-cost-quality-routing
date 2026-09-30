"""Comprehensive evaluation runner for learned model router."""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

# Ensure root, apps, and packages/core/src are in sys.path
root_dir = Path(__file__).resolve().parents[2]
for p in [str(root_dir), str(root_dir / "apps"), str(root_dir / "packages" / "core" / "src")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import joblib

from evaluation.router.metrics import compute_router_metrics
from evaluation.router.train import load_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tollgate.router.evaluate")

DATASET_PATH = Path(__file__).parent / "datasets" / "router_benchmark.json"
ARTIFACT_DIR = root_dir / "artifacts" / "router"
OUTPUT_REPORT_PATH = Path(__file__).parent / "evaluation_report.json"


def run_evaluation(
    dataset_path: Path = DATASET_PATH,
    artifact_dir: Path = ARTIFACT_DIR,
    output_path: Path = OUTPUT_REPORT_PATH,
) -> Dict[str, Any]:
    """Run full evaluation suite across thresholds and baselines."""
    model_path = artifact_dir / "model.joblib"
    metadata_path = artifact_dir / "metadata.json"

    if not model_path.exists() or not metadata_path.exists():
        raise FileNotFoundError(
            f"Model artifacts not found in {artifact_dir}. Please run train.py first."
        )

    pipeline = joblib.load(model_path)
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    X, y, raw_data = load_dataset(dataset_path)
    total_samples = len(y)

    probs = [float(p[1]) for p in pipeline.predict_proba(X)]

    # 1. Threshold sweep
    thresholds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    sweep_results = []
    for thresh in thresholds:
        preds = [1 if p >= thresh else 0 for p in probs]
        m = compute_router_metrics(y, preds, probs, thresh)
        sweep_results.append(m.to_dict())

    # 2. Baselines
    # Always Strong: preds = [0]*total
    always_strong_preds = [0] * total_samples
    always_strong_probs = [0.0] * total_samples
    always_strong_metrics = compute_router_metrics(
        y, always_strong_preds, always_strong_probs, 1.0
    ).to_dict()

    # Always Cheap: preds = [1]*total
    always_cheap_preds = [1] * total_samples
    always_cheap_probs = [1.0] * total_samples
    always_cheap_metrics = compute_router_metrics(
        y, always_cheap_preds, always_cheap_probs, 0.0
    ).to_dict()

    # Learned Router at threshold 0.5
    learned_50_preds = [1 if p >= 0.5 else 0 for p in probs]
    learned_50_metrics = compute_router_metrics(y, learned_50_preds, probs, 0.5).to_dict()

    # Learned Router at threshold 0.7 (conservative)
    learned_70_preds = [1 if p >= 0.7 else 0 for p in probs]
    learned_70_metrics = compute_router_metrics(y, learned_70_preds, probs, 0.7).to_dict()

    report = {
        "dataset_version": metadata.get("dataset_version", "1.0.0"),
        "model_version": metadata.get("model_version", "v1.0.0"),
        "total_benchmark_samples": total_samples,
        "class_distribution": {
            "cheap_sufficient": sum(y),
            "strong_required": total_samples - sum(y),
        },
        "baselines": {
            "always_strong": always_strong_metrics,
            "always_cheap": always_cheap_metrics,
            "learned_router_threshold_0_5": learned_50_metrics,
            "learned_router_threshold_0_7": learned_70_metrics,
        },
        "threshold_sweep": sweep_results,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Evaluation report exported -> {output_path}")

    # Print Summary Tables
    print("\n" + "=" * 80)
    print("                    MODEL ROUTER BENCHMARK EVALUATION")
    print("=" * 80)
    print(f"Total Samples: {total_samples} (Cheap: {sum(y)}, Strong: {total_samples - sum(y)})")
    print("\n--- BASELINE COMPARISON ---")
    print(
        f"{'Strategy':<28} | {'Accuracy':<9} | {'Precision':<9} | {'Recall':<8} | "
        f"{'FPR':<7} | {'Cost Savings':<12} | {'Quality Degradation':<18}"
    )
    print("-" * 105)
    for name, b in [
        ("Always Strong (Baseline)", always_strong_metrics),
        ("Always Cheap", always_cheap_metrics),
        ("Learned Router (t = 0.50)", learned_50_metrics),
        ("Learned Router (t = 0.70)", learned_70_metrics),
    ]:
        print(
            f"{name:<28} | {b['accuracy']:<9.3f} | {b['precision']:<9.3f} | {b['recall']:<8.3f} | "
            f"{b['false_positive_rate']:<7.3f} | {b['estimated_cost_savings_pct']:<11.1f}% | "
            f"{b['estimated_quality_degradation_pct']:<17.1f}%"
        )

    print("\n--- THRESHOLD SWEEP ---")
    print(
        f"{'Thresh':<7} | {'Accuracy':<9} | {'Precision':<9} | {'Recall':<8} | "
        f"{'F1':<7} | {'FPR':<7} | {'FNR':<7} | {'Cheap%':<7} | {'Savings%':<9}"
    )
    print("-" * 85)
    for s in sweep_results:
        print(
            f"{s['threshold']:<7.2f} | {s['accuracy']:<9.3f} | {s['precision']:<9.3f} | {s['recall']:<8.3f} | "
            f"{s['f1_score']:<7.3f} | {s['false_positive_rate']:<7.3f} | {s['false_negative_rate']:<7.3f} | "
            f"{s['cheap_route_pct']:<6.1f}% | {s['estimated_cost_savings_pct']:<8.1f}%"
        )
    print("=" * 80 + "\n")

    return report


if __name__ == "__main__":
    run_evaluation()
