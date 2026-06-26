import json
import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.common.exceptions import ProviderError, provider_call
from app.infra.llm.factory import get_llm

logger = logging.getLogger(__name__)


NoResultIntent = Literal["GENERAL_CHAT", "WORK_SUPPORT", "AMBIGUOUS"]


class NoResultDecision(BaseModel):
    intent: NoResultIntent
    answer: str | None = None

    @model_validator(mode="after")
    def answer_required_unless_work_support(self) -> "NoResultDecision":
        if self.intent != "WORK_SUPPORT" and not (self.answer or "").strip():
            raise ValueError("GENERAL_CHAT/AMBIGUOUS intent requires answer.")
        return self


_SYSTEM_PROMPT = """당신은 Workipedia 사내 챗봇의 후처리 정책 판단기입니다.

RAG와 도구 호출이 모두 실패한 상황에서, 사용자 질문을 다음 중 하나로 분류하세요.

- GENERAL_CHAT: 인사, 감사, 잡담, 일반 상식 질문처럼 티켓을 만들면 안 되는 질문
- WORK_SUPPORT: 사내 업무 문제, 계정/권한/오류/장애/처리 요청, 또는 휴가/근태/전사 휴일/복지/규정/신청/승인/사내 시설/공간/라운지/회의실/좌석/출입/이용 가능 여부처럼 사내 제도나 업무 정보에 관한 질문. 답을 못 찾으면 티켓 제안이 자연스러운 질문
- AMBIGUOUS: "이거 돼?", "언제야?", "어떻게 해?"처럼 업무 관련성이나 요청 대상이 불명확해서 추가 설명이 필요한 질문

규칙:
1. GENERAL_CHAT에는 짧고 자연스러운 한국어 답변을 작성하세요.
2. AMBIGUOUS에는 업무 관련 질문이면 더 구체적으로 알려달라는 한국어 답변을 작성하세요.
3. WORK_SUPPORT에는 answer를 null로 두세요.
4. 반드시 JSON만 반환하세요.

출력 예:
{"intent":"GENERAL_CHAT","answer":"안녕하세요. 무엇을 도와드릴까요?"}
{"intent":"WORK_SUPPORT","answer":null}
{"intent":"AMBIGUOUS","answer":"업무 관련 질문이라면 상황을 조금 더 구체적으로 알려주세요."}"""

FALLBACK_DECISION = NoResultDecision(
    intent="AMBIGUOUS",
    answer="업무 관련 질문이라면 어떤 상황에서 문제가 생겼는지 조금 더 구체적으로 알려주세요.",
)

_GENERAL_CHAT_PRECHECK_EXACT = {
    "안녕",
    "안녕하세요",
    "하이",
    "hello",
    "hi",
}
_GENERAL_CHAT_PRECHECK_HINTS = (
    "누구야",
    "이름이 뭐",
    "이름 뭐",
)
_WORK_SUPPORT_PRECHECK_KEYWORDS = (
    "계정",
    "권한",
    "오류",
    "에러",
    "장애",
    "신청",
    "승인",
    "휴가",
    "연차",
    "근태",
    "복지",
    "규정",
    "회의실",
    "라운지",
    "좌석",
    "출입",
    "티켓",
    "담당",
    "부서",
    "문서",
    "매뉴얼",
)


def _normalize_question(text: str) -> str:
    return text.strip().lower().rstrip(".!！?？~")


def should_precheck_general_chat(question: str) -> bool:
    """GENERAL_CHAT 조기 분기를 위해 정책 LLM을 먼저 호출할지 정한다.

    이 함수는 최종 intent 판정기가 아니라 비용 절감용 후보 필터다.
    최종 GENERAL_CHAT/WORK_SUPPORT/AMBIGUOUS 판정은 NoResultPolicy.decide가 한다.
    """
    normalized = _normalize_question(question)
    if normalized in _GENERAL_CHAT_PRECHECK_EXACT:
        return True
    if any(keyword in normalized for keyword in _WORK_SUPPORT_PRECHECK_KEYWORDS):
        return False
    return any(hint in normalized for hint in _GENERAL_CHAT_PRECHECK_HINTS)


def _extract_text(response) -> str:
    content = response.content
    if isinstance(content, list):
        text = " ".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    else:
        text = str(content)

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        inner = [line for line in lines[1:] if line.strip() != "```"]
        return "\n".join(inner).strip()
    return stripped


class NoResultPolicy:
    def decide(self, question: str) -> NoResultDecision:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=f"[사용자 질문]\n{question}"),
        ]

        try:
            with provider_call("llm"):
                response = get_llm(max_retries=0).invoke(messages)
            return NoResultDecision.model_validate(json.loads(_extract_text(response)))
        except (ProviderError, json.JSONDecodeError, ValidationError) as exc:
            logger.warning("no_result_policy fallback: %s", exc)
            return FALLBACK_DECISION


no_result_policy = NoResultPolicy()
