import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, model_validator

from app.common.exceptions import ProviderError, provider_call
from app.domain.tool.schemas import ToolDefinition, ToolSelection
from app.infra.llm.factory import get_llm

_SYSTEM_PROMPT = """아래 Tool 목록 중 사용자 질문에 답변하는 데 필요한 Tool을 하나 선택하고 입력 인자를 지정하라.
적합한 Tool이 없으면 selected=false로 반환하라.
입력 인자는 각 Tool의 parametersSchema에 정의된 필드만 사용할 수 있다.

반드시 아래 JSON 형식 중 하나로만 반환하라. JSON 외 다른 텍스트는 포함하지 마라.
{"selected": true, "tool_id": "<tool_id>", "inputs": {...}}
{"selected": false}"""


class _SelectorResponse(BaseModel):
    model_config = ConfigDict(strict=True)  # "false" 문자열이 bool로 강제 변환되지 않도록

    selected: bool
    tool_id: str | None = None
    inputs: dict | None = None

    @model_validator(mode="after")
    def _validate_selected_fields(self) -> "_SelectorResponse":
        if self.selected:
            if not self.tool_id:
                raise ValueError("selected=true이면 tool_id는 비어 있지 않은 문자열이어야 합니다.")
            if not isinstance(self.inputs, dict):
                raise ValueError("selected=true이면 inputs는 dict여야 합니다.")
        return self


def _tools_context(tools: list[ToolDefinition]) -> str:
    items = [
        f"- tool_id: {t.tool_id}\n  name: {t.name}\n  description: {t.description}\n  parametersSchema: {json.dumps(t.parameters_schema, ensure_ascii=False)}"
        for t in tools
    ]
    return "\n".join(items)


def _extract_text(response) -> str:
    content = response.content
    if isinstance(content, list):
        text = " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    else:
        text = str(content)
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        return "\n".join(l for l in lines[1:] if l.strip() != "```")
    return stripped


class ToolSelector:
    def select(self, query: str, tools: list[ToolDefinition]) -> ToolSelection | None:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"[Tools]\n{_tools_context(tools)}\n\n[Question]\n{query}"),
        ]
        last_error = ""
        for attempt in range(2):
            try:
                with provider_call("llm"):
                    response = get_llm().invoke(messages)
                parsed = _SelectorResponse.model_validate_json(_extract_text(response))
                if not parsed.selected:
                    return None
                return ToolSelection(tool_id=parsed.tool_id, inputs=parsed.inputs)
            except ProviderError:
                raise
            except Exception as exc:
                last_error = str(exc)
                if attempt == 1:
                    raise ProviderError("llm", f"Tool 선택 응답 파싱 실패: {last_error}") from exc
        return None  # unreachable
