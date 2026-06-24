import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.exceptions import ProviderError, provider_call
from app.domain.manual_summary.schemas import (
    ManualChangeSummaryRequest,
    ManualChangeSummaryResponse,
)
from app.infra.llm.factory import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 사내 매뉴얼·규정의 변경 내용을 요약하는 AI입니다.

매뉴얼 본문의 변경 diff가 주어지면, 어느 부분이 어떻게 바뀌었는지 사용자가 바로 이해할 수 있는 한국어 한 문장으로 요약하세요.

규칙:
- 반드시 자연스러운 한국어 평서문 한 줄로만 답합니다.
- 변경된 위치를 구체적으로 짚습니다. diff에 조·항·호·목 번호가 있으면 그대로 인용합니다.
  (예: "제3조 제2항", "제5조 제1항 제3호")
- 조·항 번호가 없으면 변경된 항목 제목이나 해당 부분을 짚어 표현합니다.
- 무엇이 어떻게 바뀌었는지(추가/삭제/수정과 그 핵심 내용)를 함께 담습니다.
- diff 기호(@@, +, -), 줄 번호, 파일 경로, 내부 코드 값은 노출하지 않습니다.
- 추측이나 과장 없이 주어진 변경 내용만 요약합니다.
- 예: "제3조 제2항의 휴가 신청 기한이 7일 전에서 3일 전으로 변경되었습니다."
- 예: "안전 점검 절차 항목에 분기별 정기 점검 내용이 추가되었습니다."
- 따옴표나 접두어 없이 문장만 출력합니다."""


def _build_user_message(request: ManualChangeSummaryRequest) -> str:
    return (
        f"[매뉴얼 제목]\n{request.title}\n\n"
        f"[변경 사유 코드]\n{request.update_reason or '미상'}\n\n"
        f"[변경 diff]\n{request.content_diff}"
    )


class ManualChangeSummaryService:
    def summarize(self, request: ManualChangeSummaryRequest) -> ManualChangeSummaryResponse:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_build_user_message(request)),
        ]

        with provider_call("llm"):
            llm = get_llm(request_timeout=30.0, max_retries=1)
            response = llm.invoke(messages)

        content = response.content if hasattr(response, "content") else str(response)
        summary = content.strip() if isinstance(content, str) else str(content).strip()
        if not summary:
            raise ProviderError("llm", "LLM이 빈 요약을 반환했습니다.")
        return ManualChangeSummaryResponse(summary=summary)


manual_summary_service = ManualChangeSummaryService()
