from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class KnowledgeSyncRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_id: int = Field(gt=0)
    source_type: Literal["DEPT_RR", "ROUTING_CASE"]
    title: str
    content: str
    department_id: int = Field(gt=0)
    department_name: str

    @field_validator("title", "content", "department_name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("공백만 포함된 값은 허용되지 않습니다.")
        return v

    @model_validator(mode="after")
    def validate_dept_rr_source_id(self) -> "KnowledgeSyncRequest":
        if self.source_type == "DEPT_RR" and self.source_id != self.department_id:
            raise ValueError("DEPT_RR 요청의 sourceId는 departmentId와 같아야 합니다.")
        return self


class KnowledgeSyncResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_id: int
    synced_chunks: int


class KnowledgeDeleteResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    source_id: int
    deleted_chunks: int
