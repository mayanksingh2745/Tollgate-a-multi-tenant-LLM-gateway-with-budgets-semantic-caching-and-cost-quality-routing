"""Benchmark Runner and Orchestration CLI for Tollgate (Phase 13).

Provides automated execution of smoke and full benchmark suites,
persisting standardized machine-readable JSON results to benchmarks/results/
and triggering automated report/chart generation.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# Ensure repository root, apps, apps/gateway, and packages/core/src are on sys.path
root_dir = Path(__file__).resolve().parents[2]
for path in [str(root_dir), str(root_dir / "apps"), str(root_dir / "apps" / "gateway"), str(root_dir / "packages" / "core" / "src")]:
    if path not in sys.path:
        sys.path.insert(0, path)

from benchmarks.scenarios.baseline import run_baseline_benchmark
from benchmarks.scenarios.budget_concurrency import run_budget_concurrency_benchmark
from benchmarks.scenarios.concurrency import run_concurrency_benchmark
from benchmarks.scenarios.exact_cache import run_exact_cache_benchmark
from benchmarks.scenarios.failure_injection import run_failure_injection_benchmark
from benchmarks.scenarios.mixed_workload import run_mixed_workload_benchmark
from benchmarks.scenarios.rate_limit_concurrency import run_ratelimit_benchmark
from benchmarks.scenarios.reliability import run_reliability_benchmark
from benchmarks.scenarios.routing import run_router_benchmark
from benchmarks.scenarios.semantic_cache import run_semantic_cache_benchmark
from benchmarks.scenarios.streaming import run_streaming_benchmark
from benchmarks.scenarios.usage_worker import run_usage_worker_benchmark
from benchmarks.scripts.generate_report import (
    generate_markdown_report,
    render_all_charts,
)


def check_security_safeguards(target_url: str | None = None) -> None:
    """Safeguard against pointing destructive load benchmarks at non-local production."""
    if target_url:
        is_local = any(h in target_url for h in ["localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver"])
        allow_external = os.getenv("TOLLGATE_BENCHMARK_ALLOW_EXTERNAL", "false").lower() in ("true", "1", "yes")
        if not is_local and not allow_external:
            raise PermissionError(
                f"SAFETY LOCKOUT: Benchmark target '{target_url}' appears to be an external/production host. "
                f"To run against non-localhost targets, explicitly set TOLLGATE_BENCHMARK_ALLOW_EXTERNAL=true."
            )


SCENARIO_RUNNERS = {
    "baseline": ("Gateway Baseline & Overhead", run_baseline_benchmark),
    "concurrency": ("Throughput & Concurrency Ladder", run_concurrency_benchmark),
    "exact_cache": ("Exact Cache Effectiveness & Correctness", run_exact_cache_benchmark),
    "semantic_cache": ("Semantic Cache Precision & Recall", run_semantic_cache_benchmark),
    "routing": ("Learned Router vs Strong/Cheap", run_router_benchmark),
    "reliability": ("Failover & Circuit Breaker", run_reliability_benchmark),
    "budget_concurrency": ("Budget Multi-Client Concurrency", run_budget_concurrency_benchmark),
    "rate_limit_concurrency": ("Rate Limiting & Tenant Isolation", run_ratelimit_benchmark),
    "usage_worker": ("Usage Worker Pipeline Throughput", run_usage_worker_benchmark),
    "streaming": ("SSE Streaming & Client Disconnects", run_streaming_benchmark),
    "failure_injection": ("Redis & PostgreSQL Failure Injection", run_failure_injection_benchmark),
    "mixed_workload": ("Realistic Mixed Production Workload", run_mixed_workload_benchmark),
}

# Smoke mode runs a subset or lighter parameters for quick PR validation
SMOKE_SCENARIOS = [
    "baseline",
    "exact_cache",
    "routing",
    "reliability",
    "budget_concurrency",
    "failure_injection",
]


async def run_scenario_wrapper(name: str, runner_func: Any, mode: str) -> Any:
    """Executes a scenario runner with mode-specific sizing."""
    print("\n========================================================")
    print(f">> [RUN] Scenario: {name} (Mode: {mode})")
    print("========================================================")

    kwargs = {}
    sig = inspect.signature(runner_func)

    if mode == "smoke":
        if "request_count" in sig.parameters:
            kwargs["request_count"] = 20
        if "warmup_count" in sig.parameters:
            kwargs["warmup_count"] = 5
        if "concurrency_levels" in sig.parameters:
            kwargs["concurrency_levels"] = [1, 5, 10]
        if "requests_per_level" in sig.parameters:
            kwargs["requests_per_level"] = 15
        if "num_concurrent_clients" in sig.parameters:
            kwargs["num_concurrent_clients"] = 10
        if "events_count" in sig.parameters:
            kwargs["events_count"] = 50
        if "duration_seconds" in sig.parameters:
            kwargs["duration_seconds"] = 3.0
    else:
        # Full mode defaults or env override
        reqs = os.getenv("TOLLGATE_BENCHMARK_REQUESTS")
        if reqs and "request_count" in sig.parameters:
            kwargs["request_count"] = int(reqs)

    if inspect.iscoroutinefunction(runner_func):
        result = await runner_func(**kwargs)
    else:
        result = runner_func(**kwargs)

    print(f"[OK] Completed {name}: Total Requests={result.requests_total}, Success={result.requests_successful}, RPS={result.throughput_rps}")
    return result


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Tollgate Benchmark Orchestration Suite")
    parser.add_argument(
        "--mode",
        choices=["smoke", "full"],
        default="smoke",
        help="Benchmark execution mode (smoke=fast PR checks, full=deep statistical suite)",
    )
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIO_RUNNERS.keys()) + ["all"],
        default="all",
        help="Specific scenario to execute or 'all'",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=root_dir / "benchmarks" / "results",
        help="Directory to save JSON benchmark results",
    )
    parser.add_argument(
        "--charts-dir",
        type=Path,
        default=root_dir / "benchmarks" / "charts",
        help="Directory to save SVG chart visualizations",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=root_dir / "docs" / "benchmark-results.md",
        help="Path for generated Markdown summary report",
    )
    parser.add_argument(
        "--target-url",
        type=str,
        default=os.getenv("TOLLGATE_BENCHMARK_BASE_URL", "http://localhost:8000"),
        help="Target gateway base URL",
    )

    args = parser.parse_args()

    # Safety checks
    check_security_safeguards(args.target_url)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.charts_dir.mkdir(parents=True, exist_ok=True)

    scenarios_to_run = []
    if args.scenario == "all":
        if args.mode == "smoke":
            scenarios_to_run = [(k, SCENARIO_RUNNERS[k][1]) for k in SMOKE_SCENARIOS]
        else:
            scenarios_to_run = [(k, SCENARIO_RUNNERS[k][1]) for k in SCENARIO_RUNNERS]
    else:
        scenarios_to_run = [(args.scenario, SCENARIO_RUNNERS[args.scenario][1])]

    print("Initiating Tollgate Benchmarks:")
    print(f"Mode: {args.mode.upper()}")
    print(f"Scenarios: {[s[0] for s in scenarios_to_run]}")
    print(f"Output Directory: {args.output_dir}")

    results = []
    for s_name, s_func in scenarios_to_run:
        try:
            res = await run_scenario_wrapper(s_name, s_func, args.mode)
            out_file = args.output_dir / f"{s_name}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(res.to_dict(), f, indent=2)
            print(f"Saved machine-readable result to: {out_file}")
            results.append(res)
        except Exception as e:
            print(f"[FAIL] Error in scenario {s_name}: {e}")
            import traceback
            traceback.print_exc()

    # Generate charts and markdown report
    print("\n========================================================")
    print(">> [RUN] Generating Visualizations and Markdown Report")
    print("========================================================")
    render_all_charts(args.output_dir, args.charts_dir)
    generate_markdown_report(args.output_dir, args.report_file, args.charts_dir)
    print(f"[OK] Benchmark report generated at: {args.report_file}")

    return 0


def main() -> None:
    code = asyncio.run(main_async())
    sys.exit(code)


if __name__ == "__main__":
    main()
