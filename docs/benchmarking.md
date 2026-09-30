# Tollgate Benchmarking & Evaluation Guide

This document describes the architecture, scenario suite, orchestration CLI, and reporting mechanisms of the **Tollgate Advanced Benchmarking & Evaluation System (Phase 13)**.

---

## 1. Overview & Principles

Tollgate's benchmarking suite is designed for **rigorous, reproducible, and verifiable engineering evaluation**.

### Core Principles
* **Real Measurements Only**: Zero fabricated, estimated, or hand-coded results. Every figure is produced by an executable scenario.
* **Deterministic Isolation**: Tests run against mock providers or controlled in-memory state with fixed random seeds (`seed=42`).
* **Multi-Percentile Rigor**: Evaluated across p50, p75, p90, p95, and p99 to expose tail latency under concurrency.
* **Safety Lockout**: The benchmark runner strictly prevents accidental load tests against production hosts.

---

## 2. Directory Layout

```text
benchmarks/
├── README.md
├── charts/                     # Generated standalone SVG visualizations
│   ├── throughput_vs_concurrency.svg
│   └── latency_vs_concurrency.svg
├── config/                     # Declarative scenario configurations
│   ├── baseline.yaml
│   ├── cache.yaml
│   ├── reliability.yaml
│   ├── routing.yaml
│   └── stress.yaml
├── results/                    # Machine-readable JSON output files
│   ├── baseline.json
│   ├── budget_concurrency.json
│   ├── concurrency.json
│   ├── exact_cache.json
│   ├── failure_injection.json
│   ├── mixed_workload.json
│   ├── rate_limit_concurrency.json
│   ├── reliability.json
│   ├── routing.json
│   ├── semantic_cache.json
│   ├── streaming.json
│   └── usage_worker.json
├── scenarios/                  # Executable benchmark scenario modules
│   ├── base.py                 # System metadata & statistical percentile math
│   ├── baseline.py             # Direct mock vs gateway latency overhead
│   ├── budget_concurrency.py   # Multi-client budget race & zero overspend
│   ├── concurrency.py          # Concurrency ladder [1, 5, 10, 25, 50, 100]
│   ├── exact_cache.py          # Exact cache hit rate, scaling & isolation
│   ├── failure_injection.py    # Redis & PostgreSQL failure resilience
│   ├── mixed_workload.py       # Realistic production traffic blend
│   ├── rate_limit_concurrency.py # Token bucket burst & tenant isolation
│   ├── reliability.py          # Provider failover & circuit breaker avoidance
│   ├── routing.py              # Phase 9 router artifact evaluation
│   ├── semantic_cache.py       # Precision, recall & adversarial false hits
│   ├── streaming.py            # SSE TTFT & early client disconnects
│   └── usage_worker.py         # Batch throughput, dead-letter & auto-claim
└── scripts/
    ├── detect_regression.py    # Automated regression detector with exit codes
    ├── generate_report.py      # Automated report & vector SVG chart builder
    └── run_benchmarks.py       # Main orchestration CLI
```

---

## 3. Running Benchmarks

### Smoke Suite (Fast PR Validation)
Runs a lightweight subset of core benchmarks (baseline, exact cache, routing, reliability, budget, failure injection) with smaller sample sizes for fast validation:

```bash
python benchmarks/scripts/run_benchmarks.py --mode smoke
```

### Full Benchmark Suite (Deep Statistical Run)
Executes all 12 evaluation scenarios across full concurrency ladders, threshold sweeps, and large event batches:

```bash
python benchmarks/scripts/run_benchmarks.py --mode full
```

### Running a Specific Scenario
```bash
python benchmarks/scripts/run_benchmarks.py --scenario exact_cache
```

---

## 4. Automated Regression Detection

Detect whether latency has increased, throughput has dropped, or error rates have degraded beyond a configurable threshold percentage:

```bash
python benchmarks/scripts/detect_regression.py \
  --baseline benchmarks/results \
  --current benchmarks/results \
  --threshold-percent 10.0
```

* Returns exit code `0` if all metrics are within tolerance.
* Returns exit code `1` if any regression exceeds the threshold percentage.

---

## 5. Configuration Reference

Environment variables supported by the benchmark runner:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `TOLLGATE_BENCHMARK_BASE_URL` | `http://localhost:8000` | Target gateway URL for HTTP integration |
| `TOLLGATE_BENCHMARK_REQUESTS` | Scenario-defined | Request count override |
| `TOLLGATE_BENCHMARK_CONCURRENCY` | Scenario-defined | Concurrency level override |
| `TOLLGATE_BENCHMARK_REGRESSION_THRESHOLD_PERCENT` | `10.0` | Regression detection percentage threshold |
| `TOLLGATE_BENCHMARK_ALLOW_EXTERNAL` | `false` | Security safeguard: must be `true` to target non-localhost URLs |

---

## 6. Output Artifacts

* **Machine-Readable JSON**: Stored in `benchmarks/results/<scenario_name>.json`.
* **Markdown Summary Report**: Generated in `docs/benchmark-results.md`.
* **Vector SVG Visualizations**: Rendered into `benchmarks/charts/`.
