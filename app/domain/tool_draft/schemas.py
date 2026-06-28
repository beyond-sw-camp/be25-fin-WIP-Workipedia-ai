from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class ToolDraftRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    endpoint_url: str
    http_method: str = "GET"

    @field_validator("endpoint_url")
    @classmethod
    def endpoint_url_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("endpointUrl은 비어있을 수 없습니다.")
        return v


class ToolDraftParameter(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str
    type: str
    description: str
    required: bool = True


class ToolDraftResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str
    description: str
    endpoint_url: str
    parameters: list[ToolDraftParameter]
