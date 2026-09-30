from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool", "function"]
    content: Optional[Union[str, List[Dict[str, Any]]]] = ""
    name: Optional[str] = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")

    @field_validator("content")
    @classmethod
    def validate_content_size(cls, v: Optional[Union[str, List[Dict[str, Any]]]]):
        if isinstance(v, str) and len(v) > 500_000:
            raise ValueError("Message content exceeds maximum allowed length of 500,000 characters.")
        elif isinstance(v, list) and len(v) > 100:
            raise ValueError("Message content parts exceed maximum allowed count of 100 parts.")
        return v


class ResponseFormat(BaseModel):
    type: Literal["text", "json_object"] = "text"

    model_config = ConfigDict(extra="forbid")


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., min_length=1, max_length=256, description="Model identifier")
    messages: List[ChatMessage] = Field(..., min_length=1, max_length=1000, description="List of messages")
    stream: bool = Field(default=False, description="Whether to stream back partial progress")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=128_000)
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=None, ge=-2.0, le=2.0)
    response_format: Optional[ResponseFormat] = None
    seed: Optional[int] = None
    n: Optional[int] = Field(default=1, ge=1, le=10)
    tools: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=64)
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    user: Optional[str] = Field(default=None, max_length=128)

    model_config = ConfigDict(extra="forbid")

    @field_validator("messages")
    @classmethod
    def validate_total_prompt_size(cls, messages: List[ChatMessage]) -> List[ChatMessage]:
        total_chars = 0
        for msg in messages:
            if isinstance(msg.content, str):
                total_chars += len(msg.content)
            elif isinstance(msg.content, list):
                total_chars += sum(len(str(part)) for part in msg.content)
            if total_chars > 2_000_000:
                raise ValueError("Total prompt size exceeds maximum allowed length of 2,000,000 characters.")
        return messages

    @field_validator("stop")
    @classmethod
    def validate_stop_sequences(cls, stop: Optional[Union[str, List[str]]]):
        if stop is not None:
            if isinstance(stop, str):
                if len(stop) > 512:
                    raise ValueError("Stop sequence exceeds maximum length of 512 characters.")
            elif isinstance(stop, list):
                if len(stop) > 16:
                    raise ValueError("Cannot specify more than 16 stop sequences.")
                for s in stop:
                    if len(s) > 512:
                        raise ValueError("Stop sequence exceeds maximum length of 512 characters.")
        return stop

    @field_validator("tools")
    @classmethod
    def validate_tool_definitions(cls, tools: Optional[List[Dict[str, Any]]]):
        if tools is not None:
            for tool in tools:
                if not isinstance(tool, dict):
                    raise ValueError("Tool definition must be an object.")
                fn = tool.get("function")
                if isinstance(fn, dict):
                    name = fn.get("name", "")
                    if len(str(name)) > 64:
                        raise ValueError("Tool function name exceeds maximum length of 64 characters.")
                    desc = fn.get("description", "")
                    if desc and len(str(desc)) > 1024:
                        raise ValueError("Tool description exceeds maximum length of 1024 characters.")
        return tools


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
