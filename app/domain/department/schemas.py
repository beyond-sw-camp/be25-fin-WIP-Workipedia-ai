from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class DepartmentTarget(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    department_id: int
    department_name: str
    current_prompt: str


class RoutingPromptRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    instruction: str
    targets: list[DepartmentTarget]

    @field_validator("instruction")
    @classmethod
    def instruction_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("instruction은 비어있을 수 없습니다.")
        return v

    @field_validator("targets")
    @classmethod
    def targets_not_empty(cls, v: list[DepartmentTarget]) -> list[DepartmentTarget]:
        if not v:
            raise ValueError("targets는 비어있을 수 없습니다.")
        return v


class DepartmentRoutingResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    department_id: int
    routing_prompt: str


class RoutingPromptResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    results: list[DepartmentRoutingResult]
