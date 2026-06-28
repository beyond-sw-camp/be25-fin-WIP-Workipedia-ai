"""사용자가 자유롭게 던진 요청 원문을 헬프데스크 티켓 초안(title/content)으로 정리한다.

RAG(챗봇 답변)와 무관한 가벼운 단일 LLM 호출이다. 결과는 FE 폼에 편집 가능한 초안으로
보여주며(자동 발행 X), 라우팅에 유리하도록 핵심 업무 키워드를 보존한다.
파싱 실패 시 원문으로 fallback 해 요청 흐름이 깨지지 않게 한다.
"""

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.exceptions import provider_call
from app.domain.ticket_draft.schemas import TicketDraftRequest, TicketDraftResponse
from app.infra.llm.factory import get_llm

logger = logging.getLogger(__name__)

_MAX_TITLE_LEN = 50

_SYSTEM_PROMPT = """당신은 사내 헬프데스크 티켓 작성 도우미입니다.

사용자가 자유롭게 던진 요청 문장을 받아, 담당자가 처리하기 좋은 "티켓 초안"으로 정리합니다.

규칙:
- title: 요청의 핵심을 담은 간결한 명사구. (예: "연차 잔여일수 문의", "사내 네트워크 연결 장애")
- content: 정중하고 명확한 1~2문장으로 요청을 정리한다.
- 사용자가 쓴 **핵심 업무 키워드(연차, 네트워크, 비품, 계정 등)는 반드시 그대로 보존**한다. 부서 라우팅에 쓰이기 때문이다.
- 사용자가 제공하지 않은 사실을 지어내지 않는다.
- 민감정보(주민번호, 카드번호 등)는 포함하지 않는다.
- 반드시 아래 JSON 형식으로만 응답한다. 다른 텍스트·코드펜스 없이.

{"title": "...", "content": "..."}

예시:
입력: "올해 연차 얼마나 써야돼?"
출력: {"title": "연차 잔여일수 문의", "content": "올해 사용 가능한 잔여 연차 일수를 확인하고 싶습니다."}
입력: "사무실 와이파이가 안돼"
출력: {"title": "사내 네트워크 연결 장애", "content": "사무실 와이파이(네트워크) 연결이 되지 않아 확인을 요청드립니다."}"""


class TicketDraftService:
    def draft(self, request: TicketDraftRequest) -> TicketDraftResponse:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=request.raw_text),
        ]
        with provider_call("llm"):
            llm = get_llm(request_timeout=20.0, max_retries=1)
            response = llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        return self._parse(content, request.raw_text)

    def _parse(self, content: str, raw_text: str) -> TicketDraftResponse:
        # 코드펜스·설명이 섞여 와도 첫 '{' ~ 마지막 '}' 구간만 떼어 JSON으로 읽는다.
        text = content.strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                title = str(data.get("title", "")).strip()
                body = str(data.get("content", "")).strip()
                if title and body:
                    return TicketDraftResponse(title=title[:_MAX_TITLE_LEN], content=body)
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass

        logger.warning("티켓 초안 파싱 실패, 원문으로 fallback 한다.")
        return self._fallback(raw_text)

    def _fallback(self, raw_text: str) -> TicketDraftResponse:
        stripped = raw_text.strip()
        first_line = stripped.splitlines()[0] if stripped else "문의"
        return TicketDraftResponse(title=first_line[:_MAX_TITLE_LEN], content=stripped)


ticket_draft_service = TicketDraftService()
