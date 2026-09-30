from typing import Optional

from pydantic import BaseModel, Field


class BudgetConfigResponse(BaseModel):
    daily_budget_microdollars: Optional[int] = Field(
        None, description="Daily spending limit in integer microdollars ($1.00 = 1,000,000)"
    )
    monthly_budget_microdollars: Optional[int] = Field(
        None, description="Monthly spending limit in integer microdollars"
    )
    currency: str = "USD"


class BudgetConfigUpdate(BaseModel):
    daily_budget_microdollars: Optional[int] = Field(
        None,
        ge=0,
        le=1_000_000_000_000_000,
        description="Daily spending limit in integer microdollars (must be >= 0 and <= 1,000,000,000,000,000)",
    )
    monthly_budget_microdollars: Optional[int] = Field(
        None,
        ge=0,
        le=1_000_000_000_000_000,
        description="Monthly spending limit in integer microdollars (must be >= 0 and <= 1,000,000,000,000,000)",
    )
