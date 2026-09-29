import asyncio
import json
import math
import sys
from pathlib import Path
from typing import List, Optional

# Setup pathing
repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
apps_dir = repo_root / "apps"
gateway_dir = apps_dir / "gateway"
core_dir = repo_root / "packages" / "core" / "src"
for p in [str(apps_dir), str(gateway_dir), str(core_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from gateway.src.cache.semantic.embeddings import (
    EmbeddingProvider,
    MockEmbeddingProvider,
)

from evaluation.semantic_cache.metrics import (
    EvaluationMetrics,
    compute_evaluation_metrics,
)


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2, strict=True))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


async def evaluate_dataset(
    dataset_path: Optional[Path] = None,
    provider: Optional[EmbeddingProvider] = None,
    thresholds: Optional[List[float]] = None,
) -> List[EvaluationMetrics]:
    if dataset_path is None:
        dataset_path = Path(__file__).resolve().parent / "datasets" / "evaluation_dataset.json"
    if provider is None:
        provider = MockEmbeddingProvider()
    if thresholds is None:
        thresholds = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Compute embeddings and similarities for all pairs once
    scored_pairs = []
    for item in data:
        vec_a = await provider.embed(item["query_a"])
        vec_b = await provider.embed(item["query_b"])
        sim = cosine_similarity(vec_a, vec_b)
        scored_pairs.append(
            {
                "category": item.get("category", "unknown"),
                "query_a": item["query_a"],
                "query_b": item["query_b"],
                "expected": item["expected_same_intent"],
                "similarity": sim,
            }
        )

    # Evaluate each threshold
    eval_results = []
    y_true = [p["expected"] for p in scored_pairs]

    for th in thresholds:
        y_pred = [p["similarity"] >= th for p in scored_pairs]
        metrics = compute_evaluation_metrics(y_true, y_pred, threshold=th)
        eval_results.append(metrics)

    return eval_results


def print_evaluation_report(results: List[EvaluationMetrics]) -> None:
    print("\n" + "=" * 92)
    print("TOLLGATE SEMANTIC CACHE — OFFLINE EVALUATION REPORT")
    print("=" * 92)
    print(
        f"{'Threshold':<11} | {'Precision':<10} | {'Recall':<10} | {'FPR':<10} | {'FNR':<10} | {'Accuracy':<10} | {'TP/FP/TN/FN':<15}"
    )
    print("-" * 92)
    for m in results:
        counts = f"{m.true_positives}/{m.false_positives}/{m.true_negatives}/{m.false_negatives}"
        print(
            f"{m.threshold:<11.2f} | {m.precision:<10.4f} | {m.recall:<10.4f} | {m.false_positive_rate:<10.4f} | {m.false_negative_rate:<10.4f} | {m.accuracy:<10.4f} | {counts:<15}"
        )
    print("=" * 92 + "\n")


if __name__ == "__main__":
    results = asyncio.run(evaluate_dataset())
    print_evaluation_report(results)
