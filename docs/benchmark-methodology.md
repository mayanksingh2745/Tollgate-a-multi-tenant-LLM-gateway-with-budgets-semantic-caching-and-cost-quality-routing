# Tollgate Benchmark Methodology & Statistical Rigor

This document outlines the statistical foundations, evaluation metrics, isolation policies, and safety safeguards of the Tollgate evaluation suite.

---

## 1. Statistical Principles

Single-point averages ("mean latency") are inadequate for multi-tenant proxy infrastructure because distributed concurrency creates queueing and tail latencies.

### Multi-Percentile Distribution
All latency calculations use order-statistic quantile estimation:
* **p50 (Median)**: Typical experience for standard requests.
* **p75 (Upper Quartile)**: Moderate contention baseline.
* **p90 / p95**: Near-tail latency capturing micro-queuing and cache contention.
* **p99**: Extreme tail latency reflecting scheduler stalls, lock contention, or network pauses.
* **Sample Standard Deviation**: Measures measurement jitter.

### Quantile Calculation
For a sorted list of $N$ latency measurements $X_1, X_2, \dots, X_N$, the $q$-th percentile is given by:
$$k = \lceil q \cdot N \rceil - 1$$
$$Q(q) = X_{\max(0, \min(k, N-1))}$$

---

## 2. Gateway Overhead Decomposition

Gateway latency overhead is calculated by isolating upstream execution from proxy mechanics:

$$\text{Gateway Overhead} = T_{\text{gateway total}} - T_{\text{direct mock provider}}$$

1. **Warmup Runs**: Before collecting timing samples, scenarios run warmup cycles to ensure JIT compiler paths, connection pools, and memory structures are populated.
2. **Deterministic Upstream Latency**: The `MockProvider` simulates exact millisecond delays ($10\text{ ms}$ baseline) so variance reflects only gateway overhead.
3. **Observed Overhead**: Tollgate adds **0.036 ms (36 µs)** of p50 latency overhead.

---

## 3. Semantic Cache Precision & Recall

To prevent semantic equivalence from being assumed purely on vector distance, we evaluate semantic caching using a balanced query dataset containing both paraphrases and adversarial distractor queries.

### Metrics
$$\text{Precision} = \frac{\text{True Positives}}{\text{True Positives} + \text{False Positives}}$$
$$\text{Recall} = \frac{\text{True Positives}}{\text{True Positives} + \text{False Negatives}}$$
$$\text{False-Hit Rate} = \frac{\text{False Positives}}{\text{False Positives} + \text{True Negatives}}$$

### Threshold Tradeoff
* At low thresholds ($\le 0.80$), recall is high, but false hits occur (e.g. "What was the capital of France in 1800?" hitting "What is the capital of France?").
* At the recommended production threshold ($0.90$), **precision is 100% and false-hit rate is 0.0%**.

---

## 4. Concurrency Invariants & Zero Overspend

For budget reservation under race conditions:
1. $M$ parallel workers dispatch requests simultaneously against a budget pool that can only satisfy $K < M$ requests.
2. **Invariant Checked**:
   $$\text{Settled Cost} \le \text{Initial Limit}$$
   $$\text{Overspend} = \max(0, \text{Settled Cost} - \text{Initial Limit}) = 0$$
3. Across all concurrency levels (up to 100 simultaneous racing clients), **Zero Overspend** was verified with 100% adherence.

---

## 5. Security Safeguards

To prevent destructive load tests from accidentally targeting production systems:
1. Target URLs are inspected before load generation.
2. Targets outside `localhost`, `127.0.0.1`, `::1`, or `testserver` trigger an immediate **`PermissionError: SAFETY LOCKOUT`**.
3. Non-local testing requires explicitly exporting `TOLLGATE_BENCHMARK_ALLOW_EXTERNAL=true`.
