import logging
import math
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger("tollgate.budgets.pricing")

# 1 USD = 1,000,000 Microdollars
MICRODOLLARS_PER_DOLLAR = 1_000_000


@dataclass(frozen=True)
class ModelPricing:
    """
    Model token pricing represented in integer microdollars per 1,000,000 tokens.
    Example: $0.15 / 1M tokens = 150,000 microdollars per 1M tokens.
    """

    input_microdollars_per_million: int
    output_microdollars_per_million: int

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> int:
        """
        Calculate total cost in integer microdollars.
        Uses ceil division to ensure we never undercharge or under-reserve fractional microdollars.
        """
        input_cost = (
            math.ceil((input_tokens * self.input_microdollars_per_million) / 1_000_000)
            if input_tokens > 0
            else 0
        )
        output_cost = (
            math.ceil((output_tokens * self.output_microdollars_per_million) / 1_000_000)
            if output_tokens > 0
            else 0
        )
        return input_cost + output_cost


class PricingService:
    """
    Centralized pricing registry and calculation service.
    Maintains versioned/configurable token prices per model.
    """

    def __init__(self):
        # Default pricing table (in microdollars per 1M tokens)
        self._pricing_table: Dict[str, ModelPricing] = {
            # Mock / Test models
            "mock-model": ModelPricing(
                input_microdollars_per_million=1_000_000,  # $1.00 / 1M tokens
                output_microdollars_per_million=2_000_000,  # $2.00 / 1M tokens
            ),
            "test-model": ModelPricing(
                input_microdollars_per_million=1_000_000,
                output_microdollars_per_million=2_000_000,
            ),
            # OpenAI Models
            "gpt-4o-mini": ModelPricing(
                input_microdollars_per_million=150_000,  # $0.15 / 1M tokens
                output_microdollars_per_million=600_000,  # $0.60 / 1M tokens
            ),
            "gpt-4o": ModelPricing(
                input_microdollars_per_million=2_500_000,  # $2.50 / 1M tokens
                output_microdollars_per_million=10_000_000,  # $10.00 / 1M tokens
            ),
            # Anthropic Models
            "claude-3-5-sonnet-20241022": ModelPricing(
                input_microdollars_per_million=3_000_000,  # $3.00 / 1M tokens
                output_microdollars_per_million=15_000_000,  # $15.00 / 1M tokens
            ),
        }
        # Fallback pricing for unconfigured models
        self._default_pricing = ModelPricing(
            input_microdollars_per_million=2_000_000,
            output_microdollars_per_million=5_000_000,
        )

    def register_pricing(self, model: str, pricing: ModelPricing) -> None:
        """Register or override pricing for a specific model."""
        self._pricing_table[model] = pricing

    def get_pricing(self, model: str, provider: Optional[str] = None) -> ModelPricing:
        """Retrieve model pricing or return default with a warning."""
        if model in self._pricing_table:
            return self._pricing_table[model]
        logger.warning(
            "No explicit pricing found for model '%s' (provider: %s); using default fallback",
            model,
            provider,
        )
        return self._default_pricing

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        provider: Optional[str] = None,
    ) -> int:
        """Calculate total request cost in integer microdollars."""
        pricing = self.get_pricing(model, provider=provider)
        return pricing.calculate_cost(input_tokens, output_tokens)


# Global singleton pricing service
pricing_service = PricingService()
