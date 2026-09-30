"""Evaluation metrics calculation for model routing benchmarks."""

from dataclasses import dataclass
from typing import List


@dataclass
class RouterEvaluationMetrics:
    """Comprehensive performance and economic metrics for router evaluation."""

    threshold: float
    total_samples: int
    true_positives: int  # Predicted cheap, cheap was sufficient
    false_positives: int  # Predicted cheap, cheap was INSUFFICIENT (quality risk!)
    true_negatives: int  # Predicted strong, cheap was insufficient (correct escalation)
    false_negatives: int  # Predicted strong, cheap was sufficient (unnecessary cost)

    accuracy: float
    precision: float
    recall: float
    f1_score: float
    false_positive_rate: float  # FP / (FP + TN)
    false_negative_rate: float  # FN / (TP + FN)
    brier_score: float

    cheap_route_pct: float
    strong_route_pct: float
    estimated_cost_savings_pct: float
    estimated_quality_degradation_pct: float

    def to_dict(self) -> dict:
        return {
            "threshold": round(self.threshold, 3),
            "total_samples": self.total_samples,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "true_negatives": self.true_negatives,
            "false_negatives": self.false_negatives,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "brier_score": round(self.brier_score, 4),
            "cheap_route_pct": round(self.cheap_route_pct, 4),
            "strong_route_pct": round(self.strong_route_pct, 4),
            "estimated_cost_savings_pct": round(self.estimated_cost_savings_pct, 4),
            "estimated_quality_degradation_pct": round(self.estimated_quality_degradation_pct, 4),
        }


def compute_router_metrics(
    y_true: List[int],
    y_pred: List[int],
    y_probs: List[float],
    threshold: float,
    cost_cheap_ratio: float = 0.15,
) -> RouterEvaluationMetrics:
    """
    Compute metrics comparing ground-truth cheap sufficiency (1 = cheap ok, 0 = strong needed)
    with router predictions (1 = routed to cheap, 0 = routed to strong).

    Args:
        y_true: Ground truth labels (1 = cheap sufficient, 0 = strong required).
        y_pred: Model predictions (1 = route cheap, 0 = route strong).
        y_probs: Predicted probabilities of class 1.
        threshold: Decision threshold used for y_pred.
        cost_cheap_ratio: Ratio of cheap model cost to strong model cost (default 0.15 = 85% cheaper).
    """
    total = len(y_true)
    if total == 0:
        return RouterEvaluationMetrics(
            threshold=threshold,
            total_samples=0,
            true_positives=0,
            false_positives=0,
            true_negatives=0,
            false_negatives=0,
            accuracy=0.0,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            false_positive_rate=0.0,
            false_negative_rate=0.0,
            brier_score=0.0,
            cheap_route_pct=0.0,
            strong_route_pct=0.0,
            estimated_cost_savings_pct=0.0,
            estimated_quality_degradation_pct=0.0,
        )

    tp = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == 1 and yp == 1)
    fp = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == 0 and yp == 1)
    tn = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == 0 and yp == 0)
    fn = sum(1 for yt, yp in zip(y_true, y_pred, strict=True) if yt == 1 and yp == 0)

    accuracy = (tp + tn) / total
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    fnr = fn / (tp + fn) if (tp + fn) > 0 else 0.0

    brier = sum((prob - yt) ** 2 for prob, yt in zip(y_probs, y_true, strict=True)) / total

    cheap_count = tp + fp
    strong_count = tn + fn
    cheap_pct = cheap_count / total
    strong_pct = strong_count / total

    # Relative to all-strong baseline:
    # Baseline cost = 1.0 * total
    # Actual cost = (cheap_count * cost_cheap_ratio) + (strong_count * 1.0)
    # Savings = 1.0 - (Actual cost / Baseline cost)
    actual_cost_ratio = (cheap_count * cost_cheap_ratio + strong_count * 1.0) / total
    cost_savings_pct = (1.0 - actual_cost_ratio) * 100.0

    # Quality degradation occurs when cheap is selected but insufficient (False Positive)
    quality_degradation_pct = (fp / total) * 100.0

    return RouterEvaluationMetrics(
        threshold=threshold,
        total_samples=total,
        true_positives=tp,
        false_positives=fp,
        true_negatives=tn,
        false_negatives=fn,
        accuracy=accuracy,
        precision=precision,
        recall=recall,
        f1_score=f1,
        false_positive_rate=fpr,
        false_negative_rate=fnr,
        brier_score=brier,
        cheap_route_pct=cheap_pct * 100.0,
        strong_route_pct=strong_pct * 100.0,
        estimated_cost_savings_pct=cost_savings_pct,
        estimated_quality_degradation_pct=quality_degradation_pct,
    )
