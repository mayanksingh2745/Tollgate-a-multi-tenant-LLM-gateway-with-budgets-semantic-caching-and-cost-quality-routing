import math
from typing import List, Optional

from gateway.src.budgets.pricing import pricing_service
from gateway.src.config import settings
from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage


def estimate_prompt_tokens(messages: List[ChatMessage]) -> int:
    """
    Deterministic bounded token estimation for chat completion input messages.
    Rule:
    - ~4 characters per token approximation
    - 4 token overhead per message for role/formatting
    - 3 token priming overhead for conversation completion
    """
    total_tokens = 3  # Conversation priming overhead
    for msg in messages:
        content = msg.content or ""
        # 1 token minimum per message content
        content_tokens = max(1, math.ceil(len(content) / 4))
        # 4 tokens overhead per message (role, turn delimiters)
        total_tokens += content_tokens + 4
    return total_tokens


def estimate_request_cost(
    request: ChatCompletionRequest,
    default_max_output_tokens: Optional[int] = None,
) -> int:
    """
    Calculate the maximum possible estimated cost in integer microdollars
    for budget reservation prior to provider execution.
    """
    max_output = (
        request.max_tokens
        if request.max_tokens is not None and request.max_tokens > 0
        else (default_max_output_tokens or settings.budget_default_max_output_tokens)
    )
    prompt_tokens = estimate_prompt_tokens(request.messages)
    return pricing_service.calculate_cost(
        model=request.model,
        input_tokens=prompt_tokens,
        output_tokens=max_output,
    )
