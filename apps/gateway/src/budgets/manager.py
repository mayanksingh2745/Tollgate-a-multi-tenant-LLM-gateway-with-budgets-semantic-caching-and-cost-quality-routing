import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from gateway.src.budgets.lua import (
    BUDGET_RELEASE_LUA,
    BUDGET_RESERVE_LUA,
    BUDGET_SETTLE_LUA,
)
from gateway.src.budgets.metrics import budget_metrics
from gateway.src.config import settings
from gateway.src.redis import get_redis_client

logger = logging.getLogger("tollgate.budgets.manager")


class BudgetBackendError(Exception):
    """Raised when the budget storage backend fails unexpectedly."""

    pass


class BudgetExceededError(Exception):
    """Raised when a request exceeds configured tenant or project budget limits."""

    def __init__(self, message: str, scope: Optional[str] = None):
        super().__init__(message)
        self.scope = scope


@dataclass
class BudgetLimits:
    tenant_daily_limit: Optional[int] = None
    tenant_monthly_limit: Optional[int] = None
    project_daily_limit: Optional[int] = None
    project_monthly_limit: Optional[int] = None


@dataclass
class ReservationResult:
    allowed: bool
    reservation_id: str
    estimated_cost: int
    rejection_reason: Optional[str] = None
    scope: Optional[str] = None


@dataclass
class SettlementResult:
    success: bool
    reservation_id: str
    estimated_cost: int
    actual_cost: int
    refund: int
    status: str


class BaseBudgetBackend(ABC):
    @abstractmethod
    async def reserve(
        self,
        tenant_id: UUID,
        project_id: UUID,
        estimated_cost: int,
        limits: BudgetLimits,
        now: Optional[float] = None,
        ttl_seconds: Optional[int] = None,
        reservation_id: Optional[str] = None,
    ) -> ReservationResult:
        pass

    @abstractmethod
    async def settle(
        self,
        reservation_id: str,
        actual_cost: int,
        now: Optional[float] = None,
    ) -> SettlementResult:
        pass

    @abstractmethod
    async def release(
        self,
        reservation_id: str,
        now: Optional[float] = None,
    ) -> bool:
        pass


class RedisBudgetBackend(BaseBudgetBackend):
    def __init__(
        self,
        redis_client: Optional[aioredis.Redis] = None,
        timeout_seconds: Optional[float] = None,
    ):
        self._client = redis_client
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.budget_redis_timeout_seconds
        )

    async def _get_client(self) -> aioredis.Redis:
        if self._client is not None:
            return self._client
        return await get_redis_client()

    def _get_period_keys(
        self,
        tenant_id: UUID,
        project_id: UUID,
        now_dt: datetime,
    ) -> Tuple[List[str], List[int]]:
        """Compute UTC daily and monthly keys and their corresponding limits."""
        day_str = now_dt.strftime("%Y-%m-%d")
        month_str = now_dt.strftime("%Y-%m")

        keys = [
            f"tg:budget:tenant:{tenant_id}:d:{day_str}",
            f"tg:budget:tenant:{tenant_id}:m:{month_str}",
            f"tg:budget:project:{project_id}:d:{day_str}",
            f"tg:budget:project:{project_id}:m:{month_str}",
        ]
        return keys

    async def reserve(
        self,
        tenant_id: UUID,
        project_id: UUID,
        estimated_cost: int,
        limits: BudgetLimits,
        now: Optional[float] = None,
        ttl_seconds: Optional[int] = None,
        reservation_id: Optional[str] = None,
    ) -> ReservationResult:
        res_id = reservation_id or str(uuid4())
        current_time = now if now is not None else time.time()
        ttl = ttl_seconds or settings.budget_reservation_ttl_seconds
        now_dt = datetime.fromtimestamp(current_time, tz=timezone.utc)

        keys = self._get_period_keys(tenant_id, project_id, now_dt)
        # Pass -1 for unlimited
        limit_values = [
            limits.tenant_daily_limit if limits.tenant_daily_limit is not None else -1,
            limits.tenant_monthly_limit if limits.tenant_monthly_limit is not None else -1,
            limits.project_daily_limit if limits.project_daily_limit is not None else -1,
            limits.project_monthly_limit if limits.project_monthly_limit is not None else -1,
        ]

        res_record_key = f"tg:reservation:{res_id}"
        all_keys = keys + [res_record_key]

        argv = (
            [str(len(keys))]
            + [str(v) for v in limit_values]
            + [
                str(estimated_cost),
                str(current_time),
                str(ttl),
                res_id,
                str(tenant_id),
                str(project_id),
            ]
        )

        client = await self._get_client()
        try:
            coro = client.eval(BUDGET_RESERVE_LUA, len(all_keys), *all_keys, *argv)
            raw_result = await asyncio.wait_for(coro, timeout=self.timeout_seconds)

            allowed_flag = int(raw_result[0])
            if allowed_flag == 1:
                return ReservationResult(
                    allowed=True,
                    reservation_id=res_id,
                    estimated_cost=estimated_cost,
                )
            else:
                reason = raw_result[1]
                scope = raw_result[2] if len(raw_result) > 2 else "budget"
                return ReservationResult(
                    allowed=False,
                    reservation_id=res_id,
                    estimated_cost=estimated_cost,
                    rejection_reason=reason,
                    scope=scope,
                )

        except (asyncio.TimeoutError, aioredis.RedisError, ConnectionError, OSError) as exc:
            logger.error("Redis budget reservation failed: %s", exc)
            raise BudgetBackendError(f"Budget backend unavailable: {exc}") from exc

    async def settle(
        self,
        reservation_id: str,
        actual_cost: int,
        now: Optional[float] = None,
    ) -> SettlementResult:
        current_time = now if now is not None else time.time()
        res_record_key = f"tg:reservation:{reservation_id}"
        client = await self._get_client()

        try:
            coro = client.eval(
                BUDGET_SETTLE_LUA,
                1,
                res_record_key,
                str(actual_cost),
                str(current_time),
            )
            raw_result = await asyncio.wait_for(coro, timeout=self.timeout_seconds)

            success_flag = int(raw_result[0])
            status_str = raw_result[1]
            refund_str = raw_result[2] if len(raw_result) > 2 else "0"
            refund = int(refund_str)

            return SettlementResult(
                success=bool(success_flag),
                reservation_id=reservation_id,
                estimated_cost=actual_cost + refund,
                actual_cost=actual_cost,
                refund=refund,
                status=status_str,
            )

        except (asyncio.TimeoutError, aioredis.RedisError, ConnectionError, OSError) as exc:
            logger.error("Redis budget settlement failed: %s", exc)
            raise BudgetBackendError(f"Budget backend unavailable: {exc}") from exc

    async def release(
        self,
        reservation_id: str,
        now: Optional[float] = None,
    ) -> bool:
        current_time = now if now is not None else time.time()
        res_record_key = f"tg:reservation:{reservation_id}"
        client = await self._get_client()

        try:
            coro = client.eval(
                BUDGET_RELEASE_LUA,
                1,
                res_record_key,
                str(current_time),
            )
            raw_result = await asyncio.wait_for(coro, timeout=self.timeout_seconds)
            return bool(int(raw_result[0]))

        except (asyncio.TimeoutError, aioredis.RedisError, ConnectionError, OSError) as exc:
            logger.error("Redis budget release failed: %s", exc)
            raise BudgetBackendError(f"Budget backend unavailable: {exc}") from exc


class InMemoryBudgetBackend(BaseBudgetBackend):
    """
    Deterministic in-memory implementation of the exact Redis token-budget Lua logic.
    Supports time injection and multi-scope isolation without requiring external Redis.
    """

    def __init__(self, now_func: Optional[Callable[[], float]] = None):
        self._lock = asyncio.Lock()
        self._now_func = now_func or time.time
        # key -> {"spent": int, "reserved": int, "res_cost": {res_id: cost}, "res_exp": {res_id: exp_ts}}
        self._buckets: Dict[str, dict] = {}
        # res_id -> {"status": str, "estimated_cost": int, "actual_cost": int, "keys": list}
        self._reservations: Dict[str, dict] = {}

    def _ensure_bucket(self, key: str) -> dict:
        if key not in self._buckets:
            self._buckets[key] = {
                "spent": 0,
                "reserved": 0,
                "res_cost": {},
                "res_exp": {},
            }
        return self._buckets[key]

    def _cleanup_expired(self, key: str, now: float) -> None:
        bucket = self._ensure_bucket(key)
        res_exp = bucket["res_exp"]
        res_cost = bucket["res_cost"]

        expired_ids = [res_id for res_id, exp_ts in res_exp.items() if exp_ts <= now]
        for res_id in expired_ids:
            cost = res_cost.pop(res_id, 0)
            res_exp.pop(res_id, None)
            bucket["reserved"] = max(0, bucket["reserved"] - cost)
            if res_id in self._reservations:
                self._reservations[res_id]["status"] = "expired"

    def _get_period_keys(self, tenant_id: UUID, project_id: UUID, now_dt: datetime) -> List[str]:
        day_str = now_dt.strftime("%Y-%m-%d")
        month_str = now_dt.strftime("%Y-%m")
        return [
            f"tg:budget:tenant:{tenant_id}:d:{day_str}",
            f"tg:budget:tenant:{tenant_id}:m:{month_str}",
            f"tg:budget:project:{project_id}:d:{day_str}",
            f"tg:budget:project:{project_id}:m:{month_str}",
        ]

    async def reserve(
        self,
        tenant_id: UUID,
        project_id: UUID,
        estimated_cost: int,
        limits: BudgetLimits,
        now: Optional[float] = None,
        ttl_seconds: Optional[int] = None,
        reservation_id: Optional[str] = None,
    ) -> ReservationResult:
        res_id = reservation_id or str(uuid4())
        current_time = now if now is not None else self._now_func()
        ttl = ttl_seconds or settings.budget_reservation_ttl_seconds
        now_dt = datetime.fromtimestamp(current_time, tz=timezone.utc)

        keys = self._get_period_keys(tenant_id, project_id, now_dt)
        limit_values = [
            limits.tenant_daily_limit,
            limits.tenant_monthly_limit,
            limits.project_daily_limit,
            limits.project_monthly_limit,
        ]

        async with self._lock:
            # 1. Clean up expired reservations on all involved keys
            for k in keys:
                self._cleanup_expired(k, current_time)

            # 2. Capacity check
            for k, limit in zip(keys, limit_values, strict=True):
                if limit is not None and limit >= 0:
                    b = self._ensure_bucket(k)
                    if (b["spent"] + b["reserved"] + estimated_cost) > limit:
                        return ReservationResult(
                            allowed=False,
                            reservation_id=res_id,
                            estimated_cost=estimated_cost,
                            rejection_reason="budget_exceeded",
                            scope=k,
                        )

            # 3. All passed -> reserve
            for k in keys:
                b = self._ensure_bucket(k)
                b["reserved"] += estimated_cost
                b["res_cost"][res_id] = estimated_cost
                b["res_exp"][res_id] = current_time + ttl

            self._reservations[res_id] = {
                "status": "reserved",
                "estimated_cost": estimated_cost,
                "actual_cost": 0,
                "keys": keys,
                "expires_at": current_time + ttl,
            }

            return ReservationResult(
                allowed=True,
                reservation_id=res_id,
                estimated_cost=estimated_cost,
            )

    async def settle(
        self,
        reservation_id: str,
        actual_cost: int,
        now: Optional[float] = None,
    ) -> SettlementResult:
        async with self._lock:
            if reservation_id not in self._reservations:
                return SettlementResult(
                    success=False,
                    reservation_id=reservation_id,
                    estimated_cost=0,
                    actual_cost=actual_cost,
                    refund=0,
                    status="reservation_not_found",
                )

            res = self._reservations[reservation_id]
            status = res["status"]

            # Idempotency checks
            if status == "settled":
                return SettlementResult(
                    success=True,
                    reservation_id=reservation_id,
                    estimated_cost=res["estimated_cost"],
                    actual_cost=res["actual_cost"],
                    refund=0,
                    status="already_settled",
                )

            if status == "released":
                return SettlementResult(
                    success=False,
                    reservation_id=reservation_id,
                    estimated_cost=res["estimated_cost"],
                    actual_cost=actual_cost,
                    refund=0,
                    status="already_released",
                )

            estimated_cost = res["estimated_cost"]
            keys = res["keys"]

            if status == "expired":
                # Reserved was already deducted upon expiration; charge spent
                for k in keys:
                    b = self._ensure_bucket(k)
                    b["spent"] += actual_cost
                res["status"] = "settled"
                res["actual_cost"] = actual_cost
                return SettlementResult(
                    success=True,
                    reservation_id=reservation_id,
                    estimated_cost=estimated_cost,
                    actual_cost=actual_cost,
                    refund=0,
                    status="settled_after_expiry",
                )

            # Normal settlement
            for k in keys:
                b = self._ensure_bucket(k)
                b["reserved"] = max(0, b["reserved"] - estimated_cost)
                b["spent"] += actual_cost
                b["res_cost"].pop(reservation_id, None)
                b["res_exp"].pop(reservation_id, None)

            refund = max(0, estimated_cost - actual_cost)
            res["status"] = "settled"
            res["actual_cost"] = actual_cost

            return SettlementResult(
                success=True,
                reservation_id=reservation_id,
                estimated_cost=estimated_cost,
                actual_cost=actual_cost,
                refund=refund,
                status="settled",
            )

    async def release(
        self,
        reservation_id: str,
        now: Optional[float] = None,
    ) -> bool:
        async with self._lock:
            if reservation_id not in self._reservations:
                return False

            res = self._reservations[reservation_id]
            status = res["status"]

            if status == "released":
                return True
            if status == "settled":
                return False
            if status == "expired":
                return True

            estimated_cost = res["estimated_cost"]
            for k in res["keys"]:
                b = self._ensure_bucket(k)
                b["reserved"] = max(0, b["reserved"] - estimated_cost)
                b["res_cost"].pop(reservation_id, None)
                b["res_exp"].pop(reservation_id, None)

            res["status"] = "released"
            return True

    def reset(self) -> None:
        self._buckets.clear()
        self._reservations.clear()


class BudgetManager:
    """
    High-level budget enforcement coordinator.
    Delegates atomic multi-scope reservation, settlement, and release to the configured backend.
    """

    def __init__(
        self,
        backend: Optional[BaseBudgetBackend] = None,
        enabled: Optional[bool] = None,
    ):
        self.backend = backend or RedisBudgetBackend()
        self.enabled = enabled if enabled is not None else settings.budget_enabled

    async def reserve(
        self,
        tenant_id: UUID,
        project_id: UUID,
        estimated_cost: int,
        limits: BudgetLimits,
        now: Optional[float] = None,
        reservation_id: Optional[str] = None,
    ) -> ReservationResult:
        if not self.enabled:
            res_id = reservation_id or str(uuid4())
            return ReservationResult(
                allowed=True,
                reservation_id=res_id,
                estimated_cost=estimated_cost,
            )

        try:
            result = await self.backend.reserve(
                tenant_id=tenant_id,
                project_id=project_id,
                estimated_cost=estimated_cost,
                limits=limits,
                now=now,
                reservation_id=reservation_id,
            )
            if result.allowed:
                budget_metrics.increment("budget_reservations_total")
            else:
                budget_metrics.increment("budget_reservation_rejections_total")
            return result
        except Exception:
            budget_metrics.increment("budget_reservation_errors_total")
            raise

    async def settle(
        self,
        reservation_id: str,
        actual_cost: int,
        now: Optional[float] = None,
    ) -> SettlementResult:
        if not self.enabled:
            return SettlementResult(
                success=True,
                reservation_id=reservation_id,
                estimated_cost=actual_cost,
                actual_cost=actual_cost,
                refund=0,
                status="settled_disabled",
            )

        try:
            result = await self.backend.settle(
                reservation_id=reservation_id,
                actual_cost=actual_cost,
                now=now,
            )
            if result.success:
                budget_metrics.increment("budget_settlements_total")
            return result
        except Exception:
            budget_metrics.increment("budget_settlement_errors_total")
            raise

    async def release(
        self,
        reservation_id: str,
        now: Optional[float] = None,
    ) -> bool:
        if not self.enabled:
            return True

        try:
            success = await self.backend.release(
                reservation_id=reservation_id,
                now=now,
            )
            if success:
                budget_metrics.increment("budget_releases_total")
            return success
        except Exception:
            raise


# Global singleton budget manager instance
budget_manager = BudgetManager()
