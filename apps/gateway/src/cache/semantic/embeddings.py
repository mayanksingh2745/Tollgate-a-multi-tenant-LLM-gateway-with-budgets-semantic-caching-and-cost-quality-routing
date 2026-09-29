import hashlib
import logging
import math
import random
import re
from abc import ABC, abstractmethod
from typing import List, Optional

import httpx
from gateway.src.config import settings

logger = logging.getLogger("tollgate.cache.semantic.embeddings")


class EmbeddingProvider(ABC):
    """
    Abstract interface for generating vector embeddings.
    """

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """
        Generates a normalized float vector embedding for the given input text.
        """
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """
        Vector embedding dimensionality.
        """
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """
        Identifier for the embedding model.
        """
        pass


class MockEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic local embedding implementation for unit/integration testing,
    CI, and offline evaluation. Requires no external network or API keys.
    Generates unit-normalized vectors with semantic stem awareness.
    """

    STOP_WORDS = {
        "a",
        "an",
        "the",
        "is",
        "in",
        "of",
        "to",
        "for",
        "with",
        "do",
        "i",
        "my",
        "you",
        "please",
        "me",
        "tell",
    }

    SYNONYMS = {
        "explain": "concept_explain",
        "describe": "concept_explain",
        "mechanism": "concept_explain",
        "work": "concept_explain",
        "how": "concept_explain",
        "what": "concept_explain",
        "behind": "concept_explain",
        "overview": "concept_explain",
        "guide": "concept_explain",
    }

    KEY_ACTION_WORDS = {
        "create",
        "delete",
        "drop",
        "insert",
        "update",
        "reset",
        "destroy",
        "make",
        "remove",
    }

    KEY_NOUN_WORDS = {
        "database",
        "table",
        "router",
        "password",
        "tcp",
        "udp",
        "congestion",
        "establishment",
        "connection",
        "auth",
        "token",
        "cache",
    }

    def __init__(self, dimension: int = 1536, model_name: str = "mock-embedding-v1"):
        self._dim = dimension
        self._model_name = model_name

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model_name

    def _get_token_vector(self, token: str) -> List[float]:
        seed = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16)
        rng = random.Random(seed)
        vec = [rng.gauss(0.0, 1.0) for _ in range(self._dim)]
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm > 0 else [0.0] * self._dim

    async def embed(self, text: str) -> List[float]:
        # Fast async return for compatibility
        tokens = re.findall(r"\b\w+\b", text.lower())
        if not tokens:
            return [0.0] * self._dim

        accum = [0.0] * self._dim
        for t in tokens:
            canonical = self.SYNONYMS.get(t, t)
            t_vec = self._get_token_vector(canonical)

            if t in self.KEY_ACTION_WORDS:
                weight = 3.5
            elif t in self.KEY_NOUN_WORDS:
                weight = 2.5
            elif t in self.STOP_WORDS:
                weight = 0.2
            else:
                weight = 1.0

            for i in range(self._dim):
                accum[i] += t_vec[i] * weight

        norm = math.sqrt(sum(x * x for x in accum))
        if norm == 0:
            return [0.0] * self._dim
        return [x / norm for x in accum]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    Production embedding provider interfacing with OpenAI or OpenAI-compatible
    embeddings endpoints (e.g. Ollama, Azure, vLLM).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        dimension: Optional[int] = None,
        timeout: Optional[float] = None,
    ):
        self._api_key = api_key or settings.embedding_api_key or ""
        self._base_url = (
            base_url or settings.embedding_api_base or "https://api.openai.com/v1"
        ).rstrip("/")
        self._model = model or settings.embedding_model
        self._dim = dimension or settings.embedding_dimension
        self._timeout = timeout or settings.embedding_timeout_seconds

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, text: str) -> List[float]:
        url = f"{self._base_url}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "input": text,
            "model": self._model,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            embedding = data["data"][0]["embedding"]
            # Normalize vector to unit length
            norm = math.sqrt(sum(x * x for x in embedding))
            if norm > 0:
                return [x / norm for x in embedding]
            return embedding


def get_embedding_provider(provider_type: Optional[str] = None) -> EmbeddingProvider:
    choice = (provider_type or settings.embedding_provider).lower()
    if choice in ("mock", "local", "test"):
        return MockEmbeddingProvider(
            dimension=settings.embedding_dimension,
            model_name=settings.embedding_model,
        )
    elif choice in ("openai", "remote"):
        return OpenAIEmbeddingProvider(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_api_base,
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
            timeout=settings.embedding_timeout_seconds,
        )
    else:
        logger.warning(
            f"Unknown embedding provider '{choice}', defaulting to MockEmbeddingProvider"
        )
        return MockEmbeddingProvider(
            dimension=settings.embedding_dimension,
            model_name=settings.embedding_model,
        )
