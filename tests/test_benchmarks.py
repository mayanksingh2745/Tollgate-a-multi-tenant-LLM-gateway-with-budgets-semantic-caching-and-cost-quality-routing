"""Unit and integration tests for the Tollgate Benchmarking & Evaluation Suite (Phase 13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.scenarios.base import (
    BenchmarkResult,
    compute_percentiles,
    get_git_commit_sha,
    get_system_environment,
)
from benchmarks.scripts.detect_regression import compare_single
from benchmarks.scripts.run_benchmarks import check_security_safeguards


def test_percentile_computation_correctness():
    # Empty list
    empty_stats = compute_percentiles([])
    assert empty_stats["count"] == 0
    assert empty_stats["p50"] == 0.0

    # Uniform list from 1 to 100
    values = [float(i) for i in range(1, 101)]
    stats = compute_percentiles(values)

    assert stats["count"] == 100
    assert stats["min"] == 1.0
    assert stats["max"] == 100.0
    assert stats["p50"] == 50.0
    assert stats["p75"] == 75.0
    assert stats["p90"] == 90.0
    assert stats["p95"] == 95.0
    assert stats["p99"] == 99.0
    assert round(stats["mean"], 1) == 50.5


def test_system_environment_and_metadata():
    env = get_system_environment()
    assert "os" in env
    assert "python_version" in env
    assert "logical_cpus" in env

    sha = get_git_commit_sha()
    assert isinstance(sha, str)
    assert len(sha) > 0


def test_benchmark_result_serialization(tmp_path: Path):
    res = BenchmarkResult(
        benchmark="test_bench",
        scenario="test_scenario",
        requests_total=10,
        requests_successful=10,
        requests_failed=0,
        duration_seconds=1.234,
        throughput_rps=8.1,
        latency_ms={"p50": 10.0, "p95": 20.0},
        details={"custom_metric": 42},
    )

    d = res.to_dict()
    assert d["benchmark"] == "test_bench"
    assert d["details"]["custom_metric"] == 42

    out_file = tmp_path / "result.json"
    out_file.write_text(json.dumps(d), encoding="utf-8")
    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert loaded["requests_total"] == 10


def test_security_safeguard_lockout():
    # Localhost targets must pass
    check_security_safeguards("http://localhost:8000")
    check_security_safeguards("http://127.0.0.1:8000")
    check_security_safeguards("http://testserver")

    # Non-local target must raise PermissionError by default
    with pytest.raises(PermissionError, match="SAFETY LOCKOUT"):
        check_security_safeguards("https://api.tollgate.production.com")


def test_regression_detection_logic():
    base = {
        "latency_ms": {"p50": 10.0, "p95": 20.0},
        "throughput_rps": 100.0,
        "error_rate": 0.01,
    }

    # Same values -> no regression
    comps_same = compare_single(base, base, threshold_percent=10.0)
    assert all(not is_reg for _, _, _, _, is_reg in comps_same)

    # 50% p95 increase -> regression flagged
    degraded = {
        "latency_ms": {"p50": 10.0, "p95": 30.0}, # +50%
        "throughput_rps": 100.0,
        "error_rate": 0.01,
    }
    comps_deg = compare_single(base, degraded, threshold_percent=10.0)
    p95_check = next(c for c in comps_deg if "p95" in c[0])
    assert p95_check[4] is True # is_regression == True

    # 30% throughput drop -> regression flagged
    slow = {
        "latency_ms": {"p50": 10.0, "p95": 20.0},
        "throughput_rps": 60.0, # -40%
        "error_rate": 0.01,
    }
    comps_slow = compare_single(base, slow, threshold_percent=10.0)
    rps_check = next(c for c in comps_slow if "Throughput" in c[0])
    assert rps_check[4] is True


@pytest.mark.asyncio
async def test_smoke_baseline_scenario():
    from benchmarks.scenarios.baseline import run_baseline_benchmark

    res = await run_baseline_benchmark(concurrency=1, request_count=5, warmup_count=2, provider_latency_seconds=0.001)
    assert res.requests_total == 5
    assert res.requests_successful == 5
    assert "overhead_ms" in res.details
