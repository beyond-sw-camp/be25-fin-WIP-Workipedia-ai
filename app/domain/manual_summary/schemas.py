from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class ManualChangeSummaryRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    title: str
    content_diff: str
    update_reason: str | None = None

    @field_validator("title", "content_diff")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("공백만 포함된 값은 허용되지 않습니다.")
        return v


class ManualChangeSummaryResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    summary: str
