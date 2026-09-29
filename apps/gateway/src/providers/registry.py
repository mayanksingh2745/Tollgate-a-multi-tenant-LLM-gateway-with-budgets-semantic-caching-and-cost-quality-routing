import os
from typing import Dict, Tuple

from gateway.src.providers.base import LLMProvider, ModelNotFoundError
from gateway.src.providers.mock import MockProvider
from gateway.src.providers.openai_compatible import OpenAICompatibleProvider


class ModelResolution:
    def __init__(self, provider: LLMProvider, upstream_model: str):
        self.provider = provider
        self.upstream_model = upstream_model


class ProviderRegistry:
    """
    Manages configured LLM providers and deterministic model routing.
    """

    def __init__(self):
        self._providers: Dict[str, LLMProvider] = {}
        self._model_routes: Dict[str, Tuple[str, str]] = (
            {}
        )  # client_model -> (provider_name, upstream_model)
        self._default_provider_name: str = "openai_compatible"
        self._initialize_defaults()

    def _initialize_defaults(self):
        base_url = os.getenv("TOLLGATE_PROVIDER_BASE_URL", "https://api.openai.com/v1")
        api_key = os.getenv("TOLLGATE_PROVIDER_API_KEY", "")
        timeout = float(os.getenv("TOLLGATE_PROVIDER_TIMEOUT_SECONDS", "60.0"))

        # Default real OpenAI-compatible provider
        openai_provider = OpenAICompatibleProvider(
            name="openai_compatible",
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
        self.register_provider(openai_provider)

        # Default mock provider for testing
        mock_provider = MockProvider(name="mock")
        self.register_provider(mock_provider)

        # Pre-configured model routes
        self._model_routes["mock-model"] = ("mock", "mock-model-v1")
        self._model_routes["mock-fast"] = ("mock", "mock-fast")
        self._model_routes["gpt-4o-mini"] = ("openai_compatible", "gpt-4o-mini")
        self._model_routes["gpt-4o"] = ("openai_compatible", "gpt-4o")
        self._model_routes["gpt-3.5-turbo"] = ("openai_compatible", "gpt-3.5-turbo")
        self._model_routes["claude-3-5-sonnet"] = ("openai_compatible", "claude-3-5-sonnet")

    def register_provider(self, provider: LLMProvider):
        self._providers[provider.name] = provider

    def register_route(self, client_model: str, provider_name: str, upstream_model: str):
        self._model_routes[client_model] = (provider_name, upstream_model)

    def resolve_model(self, client_model: str) -> ModelResolution:
        if client_model in self._model_routes:
            provider_name, upstream_model = self._model_routes[client_model]
            provider = self._providers.get(provider_name)
            if not provider:
                raise ModelNotFoundError(
                    f"Provider '{provider_name}' configured for model '{client_model}' not found"
                )
            return ModelResolution(provider=provider, upstream_model=upstream_model)

        # If model starts with mock- or test-
        if client_model.startswith("mock") or client_model.startswith("test"):
            mock_prov = self._providers.get("mock")
            if mock_prov:
                return ModelResolution(provider=mock_prov, upstream_model=client_model)

        # Pass-through to default provider if enabled, otherwise reject unknown models
        default_provider = self._providers.get(self._default_provider_name)
        if default_provider and default_provider.api_key:
            # If provider is configured with credentials, pass-through model directly
            return ModelResolution(provider=default_provider, upstream_model=client_model)

        raise ModelNotFoundError(f"The model '{client_model}' does not exist or is not configured.")


# Global provider registry instance
provider_registry = ProviderRegistry()
