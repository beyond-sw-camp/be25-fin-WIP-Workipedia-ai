import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, model_validator

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.common.masking import tool_masker as masker
from app.domain.rag.prompt import build_tool_system_prompt
from app.domain.rag.schemas import GeneratedAnswer, RagResult, RagStatus
from app.domain.tool.schemas import ToolExecutionResult
from app.infra.llm.factory import get_llm


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
            SystemMessage(content=build_tool_system_prompt(custom_prompt)),
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
