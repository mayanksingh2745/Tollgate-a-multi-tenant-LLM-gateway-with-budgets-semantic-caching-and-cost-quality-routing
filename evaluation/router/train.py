"""Train the learned model router classifier on benchmark data and save model artifact."""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure root, apps, and packages/core/src are in sys.path
root_dir = Path(__file__).resolve().parents[2]
for p in [str(root_dir), str(root_dir / "apps"), str(root_dir / "packages" / "core" / "src")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import joblib
from gateway.src.router.features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    extract_features,
)
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from evaluation.router.metrics import compute_router_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tollgate.router.train")

DATASET_PATH = Path(__file__).parent / "datasets" / "router_benchmark.json"
ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "router"


def load_dataset(
    dataset_path: Path = DATASET_PATH,
) -> Tuple[List[List[float]], List[int], List[dict]]:
    """Load benchmark dataset and extract feature vectors."""
    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    X: List[List[float]] = []
    y: List[int] = []

    for item in data:
        messages = [ChatMessage(role=m["role"], content=m["content"]) for m in item["messages"]]
        req = ChatCompletionRequest(model="test", messages=messages)
        feat = extract_features(req)
        X.append(feat.to_list())
        y.append(int(item["cheap_sufficient"]))

    return X, y, data


def train_and_export(
    dataset_path: Path = DATASET_PATH,
    artifact_dir: Path = ARTIFACT_DIR,
    model_version: str = "v1.0.0",
    dataset_version: str = "1.0.0",
    cheap_model: str = "mock-fast",
    strong_model: str = "mock-model",
    target_max_fpr: float = 0.05,
) -> Dict[str, Any]:
    """
    Train a LogisticRegression router model, select optimal threshold,
    evaluate on held-out test set, and export artifacts.
    """
    logger.info(f"Loading benchmark dataset from {dataset_path}...")
    X, y, raw_data = load_dataset(dataset_path)

    # 70% train, 15% validation, 15% test with fixed seed 42
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.30, random_state=42, stratify=y
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.50, random_state=42, stratify=y_temp
    )

    logger.info(f"Split sizes — Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

    # LogisticRegression with StandardScaler pipeline
    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    random_state=42,
                    max_iter=1000,
                    C=1.0,
                ),
            ),
        ]
    )

    pipeline.fit(X_train, y_train)

    # Threshold selection on validation set
    val_probs = [float(p[1]) for p in pipeline.predict_proba(X_val)]

    best_threshold = 0.7
    best_f1 = -1.0
    for t_step in range(50, 95, 5):
        thresh = t_step / 100.0
        preds = [1 if p >= thresh else 0 for p in val_probs]
        m = compute_router_metrics(y_val, preds, val_probs, thresh)
        # Select threshold maximizing F1 while keeping FPR bounded (prefer conservative)
        if m.false_positive_rate <= target_max_fpr:
            if m.f1_score >= best_f1:
                best_f1 = m.f1_score
                best_threshold = thresh

    if best_f1 < 0:
        # Fallback to standard 0.5 if constraint too tight on small val set
        best_threshold = 0.5

    logger.info(f"Selected optimal decision threshold: {best_threshold}")

    # Evaluate on held-out test set
    test_probs = [float(p[1]) for p in pipeline.predict_proba(X_test)]
    test_preds = [1 if p >= best_threshold else 0 for p in test_probs]
    test_metrics = compute_router_metrics(y_test, test_preds, test_probs, best_threshold)

    logger.info(
        f"Test metrics @ threshold {best_threshold:.2f} — "
        f"Accuracy: {test_metrics.accuracy:.4f}, Precision: {test_metrics.precision:.4f}, "
        f"Recall: {test_metrics.recall:.4f}, F1: {test_metrics.f1_score:.4f}, "
        f"FPR: {test_metrics.false_positive_rate:.4f}, FNR: {test_metrics.false_negative_rate:.4f}, "
        f"Cost Savings: {test_metrics.estimated_cost_savings_pct:.1f}%"
    )

    # Save artifacts
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "model.joblib"
    metadata_path = artifact_dir / "metadata.json"

    joblib.dump(pipeline, model_path)
    logger.info(f"Model artifact saved -> {model_path}")

    metadata = {
        "model_version": model_version,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "training_timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_version": dataset_version,
        "cheap_model": cheap_model,
        "strong_model": strong_model,
        "threshold": best_threshold,
        "training_config": {
            "model_type": "LogisticRegression",
            "pipeline": ["StandardScaler", "LogisticRegression"],
            "C": 1.0,
            "penalty": "l2",
            "solver": "lbfgs",
            "max_iter": 1000,
            "random_state": 42,
            "feature_names": FEATURE_NAMES,
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "test_samples": len(X_test),
        },
        "evaluation_metrics": test_metrics.to_dict(),
        "calibration": {
            "brier_score": round(test_metrics.brier_score, 4),
            "method": "sigmoid",
        },
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"Metadata artifact saved -> {metadata_path}")

    return metadata


if __name__ == "__main__":
    train_and_export()
