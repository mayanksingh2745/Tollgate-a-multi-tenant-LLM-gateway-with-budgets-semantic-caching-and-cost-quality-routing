import logging
from typing import Dict

logger = logging.getLogger("tollgate.budgets.metrics")


class BudgetMetrics:
    """
    Internal observability metrics tracker for budget operations.
    Maintains bounded cardinality counters for telemetry and monitoring.
    """

    def __init__(self):
        self._counters: Dict[str, int] = {
            "budget_reservations_total": 0,
            "budget_reservation_rejections_total": 0,
            "budget_settlements_total": 0,
            "budget_releases_total": 0,
            "budget_expirations_total": 0,
            "budget_reservation_errors_total": 0,
            "budget_settlement_errors_total": 0,
        }

    def increment(self, metric_name: str, count: int = 1) -> None:
        if metric_name in self._counters:
            self._counters[metric_name] += count
        else:
            self._counters[metric_name] = count

    def get_count(self, metric_name: str) -> int:
        return self._counters.get(metric_name, 0)

    def get_all(self) -> Dict[str, int]:
        return dict(self._counters)

    def reset(self) -> None:
        for k in self._counters:
            self._counters[k] = 0


budget_metrics = BudgetMetrics()
