"""Regression detection tool for Tollgate benchmarks.

Compares benchmark results against a baseline to flag significant performance regressions.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


def load_result(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_single(
    baseline_data: Dict[str, Any],
    current_data: Dict[str, Any],
    threshold_percent: float,
) -> List[Tuple[str, float, float, float, bool]]:
    """Compare a single baseline vs current result.

    Returns list of tuples: (metric_name, baseline_val, current_val, pct_change, is_regression)
    """
    comparisons = []

    # 1. Latency p95 (higher is worse)
    base_lat = baseline_data.get("latency_ms", {})
    curr_lat = current_data.get("latency_ms", {})
    if "p95" in base_lat and "p95" in curr_lat and base_lat["p95"] > 0:
        base_p95 = float(base_lat["p95"])
        curr_p95 = float(curr_lat["p95"])
        pct_change = ((curr_p95 - base_p95) / base_p95) * 100.0
        # If latency increases by more than threshold_percent -> regression
        is_reg = pct_change > threshold_percent
        comparisons.append(("Latency p95 (ms)", base_p95, curr_p95, pct_change, is_reg))

    # 2. Latency p50 (higher is worse)
    if "p50" in base_lat and "p50" in curr_lat and base_lat["p50"] > 0:
        base_p50 = float(base_lat["p50"])
        curr_p50 = float(curr_lat["p50"])
        pct_change = ((curr_p50 - base_p50) / base_p50) * 100.0
        is_reg = pct_change > threshold_percent
        comparisons.append(("Latency p50 (ms)", base_p50, curr_p50, pct_change, is_reg))

    # 3. Throughput RPS (lower is worse)
    base_rps = baseline_data.get("throughput_rps")
    curr_rps = current_data.get("throughput_rps")
    if base_rps is not None and curr_rps is not None and float(base_rps) > 0:
        base_r = float(base_rps)
        curr_r = float(curr_rps)
        pct_change = ((curr_r - base_r) / base_r) * 100.0
        # If throughput drops by more than threshold_percent -> regression
        is_reg = pct_change < -threshold_percent
        comparisons.append(("Throughput (RPS)", base_r, curr_r, pct_change, is_reg))

    # 4. Error rate (higher is worse)
    base_err = baseline_data.get("error_rate")
    curr_err = current_data.get("error_rate")
    if base_err is not None and curr_err is not None:
        base_e = float(base_err)
        curr_e = float(curr_err)
        diff = curr_e - base_e
        # Error rate difference threshold (e.g. +0.02 = 2% more errors)
        is_reg = diff > (threshold_percent / 100.0)
        comparisons.append(("Error Rate", base_e, curr_e, diff * 100.0, is_reg))

    return comparisons


def run_regression_check(
    baseline_path: Path,
    current_path: Path,
    threshold_percent: float,
) -> int:
    regressions_found = 0

    if baseline_path.is_file() and current_path.is_file():
        base_data = load_result(baseline_path)
        curr_data = load_result(current_path)
        name = curr_data.get("benchmark", baseline_path.stem)
        print(f"\n--- Checking {name} (Threshold: {threshold_percent}%) ---")
        comps = compare_single(base_data, curr_data, threshold_percent)
        for metric, b_val, c_val, pct, is_reg in comps:
            status = "[REGRESSION]" if is_reg else "[PASS]"
            if is_reg:
                regressions_found += 1
            print(f"  {metric:20s}: Baseline={b_val:8.2f} | Current={c_val:8.2f} | Change={pct:+6.2f}% -> {status}")

    elif baseline_path.is_dir() and current_path.is_dir():
        curr_files = {f.name: f for f in current_path.glob("*.json")}
        base_files = {f.name: f for f in baseline_path.glob("*.json")}

        common = sorted(set(curr_files.keys()).intersection(base_files.keys()))
        if not common:
            print(f"No matching benchmark JSON files between {baseline_path} and {current_path}")
            return 0

        print(f"\nComparing {len(common)} benchmark files (Threshold: {threshold_percent}%):")
        for fname in common:
            base_data = load_result(base_files[fname])
            curr_data = load_result(curr_files[fname])
            name = curr_data.get("benchmark", fname)
            print(f"\n[{name}]")
            comps = compare_single(base_data, curr_data, threshold_percent)
            for metric, b_val, c_val, pct, is_reg in comps:
                status = "[REGRESSION]" if is_reg else "[PASS]"
                if is_reg:
                    regressions_found += 1
                print(f"  {metric:20s}: Baseline={b_val:8.2f} | Current={c_val:8.2f} | Change={pct:+6.2f}% -> {status}")
    else:
        print("Both baseline and current must be either files or directories.")
        return 2

    print("\n==========================================")
    if regressions_found > 0:
        print(f"FAILED: {regressions_found} regression(s) detected exceeding {threshold_percent}% tolerance.")
        return 1
    else:
        print(f"PASSED: No regressions detected within {threshold_percent}% tolerance.")
        return 0


def main() -> None:
    default_thresh = float(os.getenv("TOLLGATE_BENCHMARK_REGRESSION_THRESHOLD_PERCENT", "10.0"))
    parser = argparse.ArgumentParser(description="Tollgate Benchmark Regression Detector")
    parser.add_argument("--baseline", required=True, type=Path, help="Path to baseline result JSON file or directory")
    parser.add_argument("--current", required=True, type=Path, help="Path to current result JSON file or directory")
    parser.add_argument(
        "--threshold-percent",
        type=float,
        default=default_thresh,
        help=f"Regression threshold percentage (default: {default_thresh}%%)",
    )

    args = parser.parse_args()
    exit_code = run_regression_check(args.baseline, args.current, args.threshold_percent)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
