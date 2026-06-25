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

매뉴얼 본문의 변경 diff가 주어지면, 한눈에 알아볼 수 있도록 변경 유형 태그를 붙인 짧은 한 줄로 요약하세요.

출력 형식:
- 반드시 `[태그] 내용` 형식의 한 줄로만 답합니다.
- 태그는 주된 변경 유형 하나를 고릅니다: [추가] [삭제] [수정] [교체]
  (내용 추가=추가, 내용 삭제=삭제, 문구·값 변경=수정, 항목 전체 교체=교체)

내용 작성 규칙:
- 군더더기 없이 핵심만 간결하게 씁니다. ("매뉴얼 제목이 ~에서 ~로" 같은 장황한 표현 금지)
- 변경된 위치를 짚습니다. diff에 조·항·호·목 번호가 있으면 그대로 인용합니다. (예: 제3조 제2항)
  번호가 없으면 변경된 항목 제목이나 해당 부분으로 표현합니다.
- 무엇이 어떻게 바뀌었는지 핵심 값/방향을 담습니다.
- 따옴표는 값을 구분해야 할 때만 작은따옴표(') 한 쌍으로 최소한만 씁니다.
- diff 기호(@@, +, -), 줄 번호, 파일 경로, 내부 코드 값은 노출하지 않습니다.
- 추측이나 과장 없이 주어진 변경 내용만 요약합니다.

예시:
- [수정] 제3조 휴가 신청 기한 7일 전 → 3일 전으로 단축
- [추가] 안전 점검 절차에 분기별 정기 점검 신설
- [삭제] 제5조 출장비 사전 승인 조항 삭제
- [수정] 제목 '워키피디아 소개서2'로 변경"""


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
