import os
from typing import Dict, List, Optional, Tuple

from gateway.src.providers.base import LLMProvider, ModelNotFoundError
from gateway.src.providers.mock import MockProvider
from gateway.src.providers.openai_compatible import OpenAICompatibleProvider
from gateway.src.reliability.policy import FallbackRoute, ProviderTarget


class ModelResolution:
    def __init__(self, provider: LLMProvider, upstream_model: str):
        self.provider = provider
        self.upstream_model = upstream_model


class ProviderRegistry:
    """
    Manages configured LLM providers, model resolution, and fallback routes.
    """

    def __init__(self):
        self._providers: Dict[str, LLMProvider] = {}
        self._model_routes: Dict[str, Tuple[str, str]] = {}
        self._fallback_routes: Dict[str, FallbackRoute] = {}
        self._default_provider_name: str = "openai_compatible"
        self._initialize_defaults()

    def _initialize_defaults(self):
        base_url = os.getenv("TOLLGATE_PROVIDER_BASE_URL", "https://api.openai.com/v1")
        api_key = os.getenv("TOLLGATE_PROVIDER_API_KEY", "")
        timeout = float(os.getenv("TOLLGATE_PROVIDER_TIMEOUT_SECONDS", "30.0"))

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

    def get_provider(self, name: str) -> Optional[LLMProvider]:
        return self._providers.get(name)

    def get_all_providers(self) -> Dict[str, LLMProvider]:
        return dict(self._providers)

    def register_route(self, client_model: str, provider_name: str, upstream_model: str):
        self._model_routes[client_model] = (provider_name, upstream_model)

    def register_fallback_route(
        self,
        client_model: str,
        primary_provider: str,
        primary_model: str,
        fallbacks: List[Tuple[str, str]],
    ):
        route = FallbackRoute(
            logical_model=client_model,
            primary=ProviderTarget(provider_name=primary_provider, upstream_model=primary_model),
            fallbacks=[
                ProviderTarget(provider_name=f_prov, upstream_model=f_model)
                for f_prov, f_model in fallbacks
            ],
        )
        self._fallback_routes[client_model] = route

    def get_route(self, client_model: str) -> FallbackRoute:
        if client_model in self._fallback_routes:
            return self._fallback_routes[client_model]

        if client_model in self._model_routes:
            provider_name, upstream_model = self._model_routes[client_model]
            return FallbackRoute(
                logical_model=client_model,
                primary=ProviderTarget(provider_name=provider_name, upstream_model=upstream_model),
                fallbacks=[],
            )

        if client_model.startswith("mock") or client_model.startswith("test"):
            return FallbackRoute(
                logical_model=client_model,
                primary=ProviderTarget(provider_name="mock", upstream_model=client_model),
                fallbacks=[],
            )

        default_provider = self._providers.get(self._default_provider_name)
        if default_provider and default_provider.api_key:
            return FallbackRoute(
                logical_model=client_model,
                primary=ProviderTarget(
                    provider_name=self._default_provider_name, upstream_model=client_model
                ),
                fallbacks=[],
            )

        raise ModelNotFoundError(f"The model '{client_model}' does not exist or is not configured.")

    def resolve_model(self, client_model: str) -> ModelResolution:
        route = self.get_route(client_model)
        provider = self._providers.get(route.primary.provider_name)
        if not provider:
            raise ModelNotFoundError(f"Provider '{route.primary.provider_name}' not configured")
        return ModelResolution(provider=provider, upstream_model=route.primary.upstream_model)


# Global provider registry instance
provider_registry = ProviderRegistry()
