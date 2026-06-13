import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from langchain_core.messages import HumanMessage, SystemMessage

import logging

from app.common.exceptions import ProviderError, provider_call

logger = logging.getLogger(__name__)
from app.core.config import RERANK_SCORE_THRESHOLD
from app.domain.rag.prompt import build_context, build_system_prompt
from app.domain.rag.schemas import GeneratedAnswer, RagResult, RagStatus, RerankedCandidate
from app.infra.llm.factory import get_llm


class _LLMAnswerSchema(BaseModel):
    status: Literal["ANSWER", "INSUFFICIENT_CONTEXT"]
    answer: str | None = None
    cited_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def answer_required_for_answer_status(self) -> "_LLMAnswerSchema":
        if self.status == "ANSWER" and not (self.answer or "").strip():
            raise ValueError("ANSWER 상태에서 answer는 비어 있을 수 없습니다.")
        return self


def _extract_text(response) -> str:
    # LangChain content는 provider에 따라 str 또는 list[dict] (Anthropic content block 등)
    content = response.content
    if isinstance(content, list):
        text = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    else:
        text = str(content)
    # Ollama 등이 ```json ... ``` 형태로 반환하는 경우 fence 제거
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner = [l for l in lines[1:] if l.strip() != "```"]
        return "\n".join(inner)
    return stripped


class RagChain:
    def generate(
        self,
        query: str,
        candidates: list[RerankedCandidate],
        custom_prompt: str | None = None,
    ) -> RagResult:
        # NO_RESULT 조건 1: 후보 없음
        if not candidates:
            return RagResult(status=RagStatus.NO_RESULT)

        # NO_RESULT 조건 2: 최고 점수가 임계값 미만 (rerank 후 rank=1이 index 0)
        if candidates[0].score < RERANK_SCORE_THRESHOLD:
            return RagResult(status=RagStatus.NO_RESULT)

        messages = [
            SystemMessage(content=build_system_prompt(custom_prompt)),
            HumanMessage(content=f"[Context]\n{build_context(candidates)}\n\n[Question]\n{query}"),
        ]

        parsed: _LLMAnswerSchema | None = None
        last_error = ""
        for attempt in range(2):
            try:
                with provider_call("llm"):
                    response = get_llm().invoke(messages)
                parsed = _LLMAnswerSchema.model_validate(json.loads(_extract_text(response)))
                break
            except ProviderError as e:
                # 네트워크/API 오류 — infra가 이미 재시도했으므로 즉시 ERROR
                return RagResult(status=RagStatus.ERROR, error_message=e.message)
            except (json.JSONDecodeError, ValidationError) as e:
                # JSON 파싱 또는 스키마 검증 실패 — 1회 재시도
                last_error = str(e)
                if attempt == 1:
                    return RagResult(status=RagStatus.ERROR, error_message=last_error)

        if parsed is None:
            return RagResult(status=RagStatus.ERROR, error_message=last_error)

        logger.warning("LLM 응답: status=%s, cited_ids=%s", parsed.status, parsed.cited_ids)

        # NO_RESULT 조건 3: LLM이 근거 없음 판단 (문자열 비교 아닌 구조화 필드)
        if parsed.status == "INSUFFICIENT_CONTEXT":
            return RagResult(status=RagStatus.NO_RESULT)

        # NO_RESULT 조건 4: cited_ids 비어 있음
        if not parsed.cited_ids:
            return RagResult(status=RagStatus.NO_RESULT)

        # NO_RESULT 조건 5: cited_ids에 없는 ID 포함 (환각 방지)
        candidate_map = {c.candidate_id: c for c in candidates}
        logger.warning("candidate_map 키: %s", list(candidate_map.keys())[:5])
        if any(cid not in candidate_map for cid in parsed.cited_ids):
            logger.warning("cited_id 불일치: %s not in candidates", [c for c in parsed.cited_ids if c not in candidate_map])
            return RagResult(status=RagStatus.NO_RESULT)

        # 중복 cited_ids 제거 (순서 유지)
        seen: set[str] = set()
        unique_ids = [cid for cid in parsed.cited_ids if not (cid in seen or seen.add(cid))]
        references = [candidate_map[cid] for cid in unique_ids]

        return RagResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(answer=parsed.answer, references=references),
        )
