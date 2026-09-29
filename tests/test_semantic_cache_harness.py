import pytest

from evaluation.semantic_cache.metrics import compute_evaluation_metrics
from evaluation.semantic_cache.runner import evaluate_dataset


@pytest.mark.asyncio
async def test_evaluation_harness_execution():
    results = await evaluate_dataset(thresholds=[0.80, 0.85, 0.90])
    assert len(results) == 3

    # At threshold 0.90, precision must be 1.0 (zero false hits)
    m90 = next(r for r in results if r.threshold == 0.90)
    assert m90.precision == 1.0
    assert m90.false_positives == 0
    assert m90.false_positive_rate == 0.0


def test_metric_computation_edge_cases():
    # All correct
    m1 = compute_evaluation_metrics([True, False], [True, False], 0.85)
    assert m1.precision == 1.0
    assert m1.recall == 1.0
    assert m1.accuracy == 1.0

    # No positives predicted
    m2 = compute_evaluation_metrics([True, True], [False, False], 0.85)
    assert m2.precision == 1.0
    assert m2.recall == 0.0
    assert m2.false_negative_rate == 1.0
