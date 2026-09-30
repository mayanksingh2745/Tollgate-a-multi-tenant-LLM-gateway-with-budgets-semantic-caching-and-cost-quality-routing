"""Cost model for the router — wraps existing PricingService with microdollar arithmetic."""

from gateway.src.budgets.pricing import ModelPricing, PricingService, pricing_service


class ModelCostProvider:
    """
    Provides normalized cost information for router economic analysis.

    Wraps the existing PricingService from Phase 5, using integer microdollars
    ($1.00 = 1,000,000) to avoid floating-point monetary drift.
    """

    def __init__(self, pricing: PricingService | None = None):
        self._pricing = pricing or pricing_service

    def input_cost_per_million_tokens(self, model: str) -> int:
        """Return input cost in microdollars per 1M tokens."""
        p = self._pricing.get_pricing(model)
        return p.input_microdollars_per_million

    def output_cost_per_million_tokens(self, model: str) -> int:
        """Return output cost in microdollars per 1M tokens."""
        p = self._pricing.get_pricing(model)
        return p.output_microdollars_per_million

    def calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> int:
        """Calculate total cost in integer microdollars."""
        return self._pricing.calculate_cost(
            model=model, input_tokens=input_tokens, output_tokens=output_tokens
        )

    def get_pricing(self, model: str) -> ModelPricing:
        """Get the ModelPricing object for a model."""
        return self._pricing.get_pricing(model)

    def estimate_cost_per_request(
        self, model: str, avg_input_tokens: int = 500, avg_output_tokens: int = 200
    ) -> int:
        """Estimate average cost per request in microdollars for economic analysis."""
        return self.calculate_cost(model, avg_input_tokens, avg_output_tokens)


# Global singleton
model_cost_provider = ModelCostProvider()
