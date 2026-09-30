"""
Base scenario definitions, system metadata extraction, and statistical calculation
for the Tollgate Benchmarking and Evaluation System (Phase 13).
"""

import math
import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# Ensure repository packages are on sys.path
root_dir = Path(__file__).resolve().parents[2]
core_src = root_dir / "packages" / "core" / "src"
apps_dir = root_dir / "apps"

for p in [str(root_dir), str(apps_dir), str(core_src)]:
    if p not in sys.path:
        sys.path.insert(0, p)


def get_git_commit_sha() -> str:
    """Retrieves current Git commit SHA safely."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def get_system_environment() -> Dict[str, Any]:
    """Captures hardware and operating system execution environment."""
    total_ram_gb = "unknown"
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total_ram_gb = round(stat.ullTotalPhys / (1024**3), 2)
        else:
            total_ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024**3), 2)
    except Exception:
        pass

    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count() or 1,
        "total_ram_gb": total_ram_gb,
        "python_version": platform.python_version(),
        "python_compiler": platform.python_compiler(),
    }


def compute_percentiles(values: List[float]) -> Dict[str, float]:
    """
    Computes rigorous statistical percentiles (p50, p75, p90, p95, p99, min, max, mean, stddev)
    from a list of float measurements.
    """
    if not values:
        return {
            "count": 0,
            "mean": 0.0,
            "stddev": 0.0,
            "min": 0.0,
            "p50": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }

    sorted_vals = sorted(values)
    n = len(sorted_vals)

    def _quantile(q: float) -> float:
        idx = int(math.ceil(q * n)) - 1
        return sorted_vals[max(0, min(idx, n - 1))]

    mean_val = sum(sorted_vals) / n
    variance = sum((x - mean_val) ** 2 for x in sorted_vals) / n if n > 1 else 0.0

    return {
        "count": n,
        "mean": round(mean_val, 3),
        "stddev": round(math.sqrt(variance), 3),
        "min": round(sorted_vals[0], 3),
        "p50": round(_quantile(0.50), 3),
        "p75": round(_quantile(0.75), 3),
        "p90": round(_quantile(0.90), 3),
        "p95": round(_quantile(0.95), 3),
        "p99": round(_quantile(0.99), 3),
        "max": round(sorted_vals[-1], 3),
    }


@dataclass
class BenchmarkResult:
    """Standardized machine-readable result schema for all Phase 13 benchmarks."""

    benchmark: str
    scenario: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    git_sha: str = field(default_factory=get_git_commit_sha)
    environment: Dict[str, Any] = field(default_factory=get_system_environment)
    configuration: Dict[str, Any] = field(default_factory=dict)
    requests_total: int = 0
    requests_successful: int = 0
    requests_failed: int = 0
    duration_seconds: float = 0.0
    throughput_rps: float = 0.0
    latency_ms: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
