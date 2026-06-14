from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class TicketRoutingRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    title: str
    content: str
    source_chatbot_message_id: int | None = None

    @field_validator("title", "content")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("공백만 포함된 값은 허용되지 않습니다.")
        return v


class CandidateDepartment(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    department_id: int
    department_name: str
    confidence_score: float


class TicketRoutingResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    assigned_department_id: int | None = None
    assigned_department_name: str | None = None
    confidence_score: float | None = None
    score_margin: float | None = None
    decision: str
    reasons: list[str]
    candidate_departments: list[CandidateDepartment]
    model: str
    provider: str
