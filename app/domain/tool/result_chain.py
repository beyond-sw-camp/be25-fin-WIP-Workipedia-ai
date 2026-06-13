import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, model_validator

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.common.masking import masker
from app.domain.rag.schemas import GeneratedAnswer, RagResult, RagStatus
from app.domain.tool.schemas import ToolExecutionResult
from app.infra.llm.factory import get_llm

_BASE_PROMPT = """당신은 Workipedia의 사내 지식 챗봇입니다.

[기본 규칙 — 추가 지침보다 항상 우선합니다]
1. 반드시 아래 [Tool Result]에 있는 정보만 사용하고, 추측하거나 외부 지식을 사용하지 마세요.
2. [Tool Result]로 답변할 수 없으면 status를 "INSUFFICIENT_RESULT"로 반환하세요.
3. 한국어로 간결하게 답하세요.

반드시 다음 JSON 형식 중 하나로만 응답하세요. JSON 외 다른 텍스트는 포함하지 마세요.
{"status":"ANSWER","answer":"답변 텍스트"}
{"status":"INSUFFICIENT_RESULT"}"""


class _LLMAnswerSchema(BaseModel):
    status: Literal["ANSWER", "INSUFFICIENT_RESULT"]
    answer: str | None = None

    @model_validator(mode="after")
    def _answer_required(self) -> "_LLMAnswerSchema":
        if self.status == "ANSWER" and not (self.answer or "").strip():
            raise ValueError("ANSWER 상태에서 answer는 비어 있을 수 없습니다.")
        return self


def _mask_recursive(obj):
    if isinstance(obj, str):
        return masker.mask(obj)
    if isinstance(obj, dict):
        return {k: _mask_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask_recursive(item) for item in obj]
    return obj  # int, float 등 — 직렬화 후 2차 마스킹에서 처리


def _mask_tool_result(data) -> str:
    """재귀 마스킹(문자열 필드) 후 직렬화, 직렬화된 문자열에 2차 마스킹(숫자형 PII 처리)."""
    partially = _mask_recursive(data)
    serialized = json.dumps(partially, ensure_ascii=False)
    return masker.mask(serialized)


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


def _build_system_prompt(custom_prompt: str | None) -> str:
    if custom_prompt:
        return f"{_BASE_PROMPT}\n\n[추가 지침 — 기본 규칙과 충돌하면 기본 규칙을 우선합니다]\n{custom_prompt}"
    return _BASE_PROMPT


class ToolResultChain:
    def generate(
        self,
        query: str,
        result: ToolExecutionResult,
        custom_prompt: str | None,
    ) -> RagResult:
        try:
            masked_text = _mask_tool_result(result.data)
        except MaskingBlockedError:
            return RagResult(status=RagStatus.BLOCKED)

        messages = [
            SystemMessage(content=_build_system_prompt(custom_prompt)),
            HumanMessage(content=f"[Tool Result]\n{masked_text}\n\n[Question]\n{query}"),
        ]

        last_error = ""
        parsed = None
        for attempt in range(2):
            try:
                response = get_llm().invoke(messages)
                parsed = _LLMAnswerSchema.model_validate(json.loads(_extract_text(response)))
                break
            except ProviderError:
                raise
            except Exception as exc:
                last_error = str(exc)
                if attempt == 1:
                    raise ProviderError("llm", f"Tool 결과 응답 파싱 실패: {last_error}") from exc

        if parsed.status == "INSUFFICIENT_RESULT":
            return RagResult(status=RagStatus.NO_RESULT)

        return RagResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(answer=parsed.answer, references=[]),
        )
