from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel


class TicketDraftRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # 사용자가 자유롭게 입력한 요청 원문. (예: "올해 연차 얼마나 써야돼?")
    raw_text: str

    @field_validator("raw_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("공백만 포함된 값은 허용되지 않습니다.")
        return v


class TicketDraftResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    # 헬프데스크 티켓 초안. 사용자는 폼에서 그대로 수정할 수 있다.
    title: str
    content: str
