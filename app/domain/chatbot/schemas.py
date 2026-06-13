from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)


class SourceItem(BaseModel):
    candidate_id: str
    source_type: str
    source_id: str
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
