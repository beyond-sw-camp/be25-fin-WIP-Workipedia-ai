import json
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from app.domain.chatbot.schemas import SessionMessage
from pydantic import BaseModel, model_validator

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.common.masking import masker
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
        session_context: list[SessionMessage] | None = None,
    ) -> RagResult:
        tool_text = json.dumps(result.data, ensure_ascii=False)

        history_messages = []
        for msg in (session_context or []):
            if msg.sender_type == "USER":
                history_messages.append(HumanMessage(content=msg.content))
            else:
                history_messages.append(AIMessage(content=msg.content))

        messages = [
            SystemMessage(content=build_tool_system_prompt(custom_prompt)),
            *history_messages,
            HumanMessage(content=f"[Tool Result]\n{tool_text}\n\n[Question]\n{query}"),
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

        try:
            masked_answer = masker.mask(parsed.answer)
        except MaskingBlockedError:
            return RagResult(status=RagStatus.BLOCKED)
        return RagResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(answer=masked_answer, references=[]),
        )
