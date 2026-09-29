from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool", "function"]
    content: Optional[Union[str, List[Dict[str, Any]]]] = ""
    name: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class ResponseFormat(BaseModel):
    type: Literal["text", "json_object"] = "text"

    model_config = ConfigDict(extra="forbid")


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., min_length=1, description="Model identifier")
    messages: List[ChatMessage] = Field(..., min_length=1, description="List of messages")
    stream: bool = Field(default=False, description="Whether to stream back partial progress")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    response_format: Optional[ResponseFormat] = None
    seed: Optional[int] = None
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    user: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatChoiceMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = ""


class ChatChoice(BaseModel):
    index: int = 0
    message: ChatChoiceMessage
    finish_reason: Optional[str] = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatChoice]
    usage: Optional[UsageInfo] = None


class ChatChunkDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class ChatChunkChoice(BaseModel):
    index: int = 0
    delta: ChatChunkDelta
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[ChatChunkChoice]
    usage: Optional[UsageInfo] = None


class OpenAIErrorDetail(BaseModel):
    message: str
    type: str = "invalid_request_error"
    param: Optional[str] = None
    code: Optional[str] = None


class OpenAIErrorResponse(BaseModel):
    error: OpenAIErrorDetail
