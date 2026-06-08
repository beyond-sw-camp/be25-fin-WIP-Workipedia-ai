from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=4, ge=1, le=20)


class SourceItem(BaseModel):
    title: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem]
    route: str | None = None
