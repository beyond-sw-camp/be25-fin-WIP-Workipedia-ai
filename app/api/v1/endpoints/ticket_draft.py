import logging

from fastapi import APIRouter, HTTPException

from app.common.exceptions import ProviderError
from app.domain.ticket_draft.schemas import TicketDraftRequest, TicketDraftResponse
from app.domain.ticket_draft.service import ticket_draft_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["ticket-draft"])


@router.post("/draft", response_model=TicketDraftResponse, response_model_by_alias=True)
def draft_ticket(request: TicketDraftRequest) -> TicketDraftResponse:
    try:
        return ticket_draft_service.draft(request)
    except ProviderError as e:
        logger.error("티켓 초안 provider 오류: [%s] %s", e.provider, e.message)
        raise HTTPException(status_code=500, detail="티켓 초안 생성 중 오류가 발생했습니다.")
