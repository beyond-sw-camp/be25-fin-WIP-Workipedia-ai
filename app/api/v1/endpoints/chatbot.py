import logging

from fastapi import APIRouter, HTTPException

from app.domain.chatbot.schemas import ChatRequest, ChatResponse, SourceItem, StepHistoryItem
from app.domain.chatbot.service import chatbot_service
from app.domain.rag.schemas import RagStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chatbot"])

_ERROR_MESSAGE = "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."


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
        title=ref.metadata.get("title", ref.candidate_id),
        score=ref.score,
        link=ref.metadata.get("link"),
    )


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
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
        sources = [_to_source_item(ref) for ref in result.answer.references]
        return ChatResponse(
            answer=result.answer.answer,
            sources=sources,
            route=result.route,
            step_history=_to_step_history(result.step_history),
        )

    return ChatResponse(answer="", sources=[], route=None, action=result.action, step_history=_to_step_history(result.step_history))
