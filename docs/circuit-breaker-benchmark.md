# Circuit Breaker Benchmark & Performance Analysis

This document details the latency, throughput, and failover overhead measurements for the **Tollgate Phase 12 Circuit Breaker & Adaptive Provider Health System**.

All measurements were taken using the benchmark suite in [`benchmarks/benchmark_circuit_breaker.py`](../benchmarks/benchmark_circuit_breaker.py).

---

## 1. Executive Summary

| Scenario | Metric | Measured Value | Target SLA | Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **Healthy Check (CLOSED)** | p50 Overhead | **3.70 µs** | < 100 µs | **Pass (< 4% of SLA)** |
| **Healthy Check (CLOSED)** | p99 Overhead | **30.20 µs** | < 500 µs | **Pass (< 7% of SLA)** |
| **Healthy Throughput** | Ops/Sec | **199,723 ops/s** | > 10,000 ops/s | **Pass (20x SLA)** |
| **Fast-Rejection (OPEN)** | Latency | **2.40 µs (p50)** | < 100 µs | **Pass (>1,000,000x faster than timeout)** |
| **Fast-Rejection (OPEN)** | Throughput | **216,640 ops/s** | > 20,000 ops/s | **Pass (10x SLA)** |
| **Contention (100 coroutines)**| Throughput | **381,042 ops/s** | > 50,000 ops/s | **Pass (7x SLA)** |

---

## 2. Microbenchmark Results

### 2.1 Healthy (CLOSED) Circuit Overhead

When upstream providers are operating normally, every incoming request passes through the circuit breaker's `before_call` verification. The circuit breaker must introduce negligible overhead.

* **Sample Size**: 10,000 sequential iterations
* **Mean Latency**: 5.01 µs
* **Median (p50)**: 3.70 µs
* **95th Percentile (p95)**: 7.10 µs
* **99th Percentile (p99)**: 30.20 µs
* **Throughput**: 199,723 ops/sec

> **Takeaway**: With a median overhead of under **4 microseconds**, the circuit breaker adds effectively zero perceptible latency to incoming LLM requests (typical LLM network latency is 200 ms to 15,000 ms).

---

### 2.2 Fast-Rejection (OPEN) Circuit Latency

When an upstream provider has failed repeatedly and tripped the circuit to `OPEN`, Tollgate rejects or immediately routes past the failing target to a healthy fallback provider without waiting for network timeouts.

* **Sample Size**: 10,000 sequential iterations
* **Mean Latency**: 4.62 µs
* **Median (p50)**: 2.40 µs
* **95th Percentile (p95)**: 7.50 µs
* **99th Percentile (p99)**: 10.70 µs
* **Throughput**: 216,640 ops/sec

#### Latency Savings Analysis

| Metric | Without Circuit Breaker (Timeout) | With Circuit Breaker (Fast-Rejection) | Improvement Factor |
| :--- | :--- | :--- | :--- |
| **Latency per Request** | 5,000 ms to 30,000 ms | **0.0024 ms** | **~2,000,000x faster** |
| **Gateway Worker Block**| Blocked waiting on socket | Zero socket allocation | Eliminates thread pool starvation |
| **Fallback Latency** | Timeout + Fallback time | 0 ms + Fallback time | User perceives immediate fallback |

---

### 2.3 Concurrency & Lock Contention Analysis

To evaluate asyncio lock contention, 100 concurrent coroutines dispatched 20,000 total circuit decisions.

* **Total Coroutines**: 100
* **Total Operations**: 20,000
* **Mean Latency**: 2.37 µs
* **Median (p50)**: 2.00 µs
* **95th Percentile (p95)**: 3.70 µs
* **99th Percentile (p99)**: 3.90 µs
* **Aggregated Throughput**: 381,042 ops/sec

> **Takeaway**: Granular per-circuit locks (`asyncio.Lock` per `provider:model` pair) prevent global contention. Even under 100 concurrent coroutines, the p99 latency remains under 4 microseconds.

---

## 3. Memory & Resource Footprint

* **Key Cardinality**: Strictly bounded to `provider:model` pairs (e.g. `openai:gpt-4o`, `anthropic:claude-3-5-sonnet`). With 10 configured providers and 5 models each, total circuit count is at most 50.
* **Per-Circuit Memory**:
  * Deque size bounded by `failure_threshold` (default: 5 timestamps ~ 40 bytes)
  * State metadata: ~200 bytes per circuit
  * Total in-memory footprint for 50 circuits: **< 15 KB**
* **Garbage Collection Pressure**: Negligible (zero heap allocation in happy path).

---

## 4. Operational Recommendations

1. **Failure Threshold (`TOLLGATE_CIRCUIT_FAILURE_THRESHOLD`)**: Default `5` is optimal for production. Setting below 3 may cause flapping during momentary network blips.
2. **Failure Window (`TOLLGATE_CIRCUIT_FAILURE_WINDOW_SECONDS`)**: Default `30.0s` gives adequate time to absorb isolated 5xx errors while quickly catching sustained outage spikes.
3. **Open Duration (`TOLLGATE_CIRCUIT_OPEN_DURATION_SECONDS`)**: Default `30.0s` gives upstream providers adequate time to recover before sending probe traffic.
4. **Rate Limit Threshold (`TOLLGATE_CIRCUIT_RATE_LIMIT_THRESHOLD`)**: Default `10` consecutive 429s ensures isolated tenant bursts do not erroneously trip the provider circuit for all other tenants.
