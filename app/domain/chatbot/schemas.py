from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class SessionMessage(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    message_id: int = Field(gt=0)
    sender_type: Literal["USER", "ASSISTANT"]
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("공백만 포함된 값은 허용되지 않습니다.")
        return v


class ChatRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    question: str = Field(min_length=1, max_length=2000)
    custom_prompt: str | None = Field(default=None, max_length=4000)
    session_context: list[SessionMessage] = Field(default_factory=list)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("공백만 포함된 값은 허용되지 않습니다.")
        return v


class SourceItem(BaseModel):
    candidate_id: str
    source_type: str
    source_id: str
    chunk_index: int | None = None
    title: str
    score: float
    link: str | None = None


class StepHistoryItem(BaseModel):
    step: str
    status: str
    error_message: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    route: str | None = None
    action: str | None = None
    step_history: list[StepHistoryItem] = []
