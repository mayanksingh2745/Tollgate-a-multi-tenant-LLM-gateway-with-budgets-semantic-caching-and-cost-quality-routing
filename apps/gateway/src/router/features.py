"""Feature extraction from ChatCompletionRequest for router inference."""

import re
from dataclasses import dataclass
from typing import List

from gateway.src.schemas.chat import ChatCompletionRequest, ChatMessage

FEATURE_SCHEMA_VERSION = 1

# Feature names in deterministic order (must match training)
FEATURE_NAMES = [
    "token_count_estimate",
    "char_count",
    "message_count",
    "user_turn_count",
    "system_message_count",
    "avg_message_length",
    "max_message_length",
    "question_mark_count",
    "has_code_block",
    "has_json_structure",
    "has_sql_keywords",
    "has_math_symbols",
    "has_url",
    "conversation_depth",
    "last_user_message_length",
]

_SQL_PATTERN = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|FROM|WHERE|JOIN|GROUP BY|ORDER BY)\b",
    re.IGNORECASE,
)
_MATH_PATTERN = re.compile(r"[+\-*/=<>≤≥√∑∏∫±×÷]|\d+\s*[+\-*/]\s*\d+")
_URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)
_CODE_BLOCK_PATTERN = re.compile(r"```")
_JSON_PATTERN = re.compile(r"\{[^}]*\}")


def _get_message_text(msg: ChatMessage) -> str:
    """Extract text content from a ChatMessage, handling string and list content."""
    if msg.content is None:
        return ""
    if isinstance(msg.content, str):
        return msg.content
    # List content (e.g. multimodal) — extract text parts
    parts = []
    for part in msg.content:
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(part.get("text", ""))
    return " ".join(parts)


@dataclass
class RequestFeatures:
    """Extracted feature vector for a single request."""

    values: List[float]
    schema_version: int = FEATURE_SCHEMA_VERSION

    def to_list(self) -> List[float]:
        return list(self.values)


def extract_features(request: ChatCompletionRequest) -> RequestFeatures:
    """
    Extract a fixed-size feature vector from a ChatCompletionRequest.

    Features are designed to be available before calling any provider,
    and capture prompt structure, complexity signals, and task-type indicators.

    Returns:
        RequestFeatures with a deterministic feature vector of length len(FEATURE_NAMES).
    """
    messages = request.messages or []
    all_texts: List[str] = []
    message_lengths: List[int] = []
    user_turn_count = 0
    system_message_count = 0
    last_user_message_length = 0

    for msg in messages:
        text = _get_message_text(msg)
        all_texts.append(text)
        message_lengths.append(len(text))

        if msg.role == "user":
            user_turn_count += 1
            last_user_message_length = len(text)
        elif msg.role == "system":
            system_message_count += 1

    combined_text = "\n".join(all_texts)
    char_count = len(combined_text)
    message_count = len(messages)
    avg_message_length = char_count / max(message_count, 1)
    max_message_length = max(message_lengths) if message_lengths else 0

    # Approximate token count (~4 chars per token, rough but deterministic)
    token_count_estimate = max(char_count // 4, 1)

    # Structural signals
    question_mark_count = combined_text.count("?")
    has_code_block = 1.0 if _CODE_BLOCK_PATTERN.search(combined_text) else 0.0
    has_json_structure = 1.0 if _JSON_PATTERN.search(combined_text) else 0.0
    has_sql_keywords = 1.0 if _SQL_PATTERN.search(combined_text) else 0.0
    has_math_symbols = 1.0 if _MATH_PATTERN.search(combined_text) else 0.0
    has_url = 1.0 if _URL_PATTERN.search(combined_text) else 0.0

    # Conversation depth: count user↔assistant turn pairs
    conversation_depth = 0
    prev_role = None
    for msg in messages:
        if msg.role == "assistant" and prev_role == "user":
            conversation_depth += 1
        prev_role = msg.role

    values = [
        float(token_count_estimate),
        float(char_count),
        float(message_count),
        float(user_turn_count),
        float(system_message_count),
        float(avg_message_length),
        float(max_message_length),
        float(question_mark_count),
        has_code_block,
        has_json_structure,
        has_sql_keywords,
        has_math_symbols,
        has_url,
        float(conversation_depth),
        float(last_user_message_length),
    ]

    return RequestFeatures(values=values, schema_version=FEATURE_SCHEMA_VERSION)
