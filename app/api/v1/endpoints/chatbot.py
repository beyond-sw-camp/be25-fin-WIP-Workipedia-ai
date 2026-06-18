import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.common.request_context import set_request_id
from app.domain.chatbot.schemas import ChatRequest, ChatResponse, SourceItem, StepHistoryItem
from app.domain.chatbot.service import chatbot_service
from app.domain.chatbot.stream import DoneEvent, ErrorEvent, StreamEvent, TokenEvent
from app.domain.rag.schemas import RagStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chatbot"])

_ERROR_MESSAGE = "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
_CREATE_TICKET_MESSAGE = "관련 문서를 찾지 못했어요. 티켓으로 문의할까요?"

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # nginx 등 프록시 버퍼링 비활성화
}


def _to_step_history(history) -> list[StepHistoryItem]:
    return [StepHistoryItem(step=s.step, status=s.status.value, error_message=s.error_message) for s in history]


def _extract_chunk_index(raw: object, parts: list[str]) -> int | None:
    """metadata 값 우선, 실패하면 candidate_id 파싱 fallback. 음수이면 None."""
    if raw is not None:
        try:
            v = int(raw)
            if v >= 0:
                return v
        except (ValueError, TypeError):
            pass
    if len(parts) == 3:
        try:
            v = int(parts[2])
            if v >= 0:
                return v
        except (ValueError, TypeError):
            pass
    return None


def _extract_positive_int(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        value = int(raw)
    except (ValueError, TypeError):
        return None
    return value if value > 0 else None


def _to_source_item(ref) -> SourceItem:
    parts = ref.candidate_id.split(":", 2)
    parsed_source_type = parts[0] if len(parts) > 1 else ""
    parsed_source_id = parts[1] if len(parts) > 1 else ""
    source_type = str(ref.metadata.get("source_type") or parsed_source_type)
    source_id = str(ref.metadata.get("source_id") or parsed_source_id)
    if not source_type or not source_id:
        raise ValueError(f"출처 정보를 확인할 수 없는 candidate: {ref.candidate_id!r}")
    chunk_index = _extract_chunk_index(ref.metadata.get("chunk_index"), parts)
    return SourceItem(
        candidate_id=ref.candidate_id,
        source_type=source_type,
        source_id=source_id,
        chunk_index=chunk_index,
        page_start=_extract_positive_int(ref.metadata.get("page_start") or ref.metadata.get("pageStart")),
        page_end=_extract_positive_int(ref.metadata.get("page_end") or ref.metadata.get("pageEnd")),
        title=ref.metadata.get("title", ref.candidate_id),
        score=ref.score,
    )


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    set_request_id()
    result = await chatbot_service.ask(
        request.question,
        custom_prompt=request.custom_prompt,
        session_context=request.session_context,
    )
    logger.warning("step_history: %s", _to_step_history(result.step_history))

    if result.status == RagStatus.BLOCKED:
        raise HTTPException(status_code=400, detail="요청을 처리할 수 없습니다.")

    if result.status == RagStatus.ERROR:
        return ChatResponse(answer=_ERROR_MESSAGE, sources=[], route=None, step_history=_to_step_history(result.step_history))

    if result.status == RagStatus.SUCCESS and result.answer:
        sources = []
        for ref in result.answer.references:
            try:
                sources.append(_to_source_item(ref))
            except ValueError as e:
                logger.warning("출처 변환 실패, sources에서 제외: %s", e)
        return ChatResponse(
            answer=result.answer.answer,
            sources=sources,
            route=result.route,
            action=result.action,
            step_history=_to_step_history(result.step_history),
        )

    answer = _CREATE_TICKET_MESSAGE if result.action == "CREATE_TICKET" else ""
    return ChatResponse(answer=answer, sources=[], route=None, action=result.action, step_history=_to_step_history(result.step_history))


def _format_sse(event: StreamEvent) -> str:
    """내부 스트림 이벤트를 SSE `data:` 프레임으로 직렬화한다."""
    if isinstance(event, TokenEvent):
        payload = {"type": "token", "content": event.content}
    elif isinstance(event, DoneEvent):
        sources_list = []
        for ref in event.references:
            try:
                sources_list.append(_to_source_item(ref).model_dump())
            except ValueError as e:
                logger.warning("출처 변환 실패, sources에서 제외: %s", e)
        payload = {
            "type": "done",
            "route": event.route,
            "action": event.action,
            "sources": sources_list,
            "step_history": [item.model_dump() for item in _to_step_history(event.step_history)],
        }
    else:  # ErrorEvent
        payload = {"type": "error", "message": event.message}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    set_request_id()

    async def event_gen():
        try:
            async for event in chatbot_service.ask_stream(
                request.question,
                custom_prompt=request.custom_prompt,
                session_context=request.session_context,
            ):
                yield _format_sse(event)
        except Exception as exc:  # 스트림 시작 전/도중의 예기치 못한 오류
            logger.error("chat_stream 실패: %s", exc)
            yield _format_sse(ErrorEvent(message=_ERROR_MESSAGE))

    return StreamingResponse(event_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)
