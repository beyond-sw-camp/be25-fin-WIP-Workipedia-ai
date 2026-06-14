import logging

from fastapi import APIRouter, HTTPException

from app.common.exceptions import ProviderError
from app.domain.ticket_routing.schemas import TicketRoutingRequest, TicketRoutingResponse
from app.domain.ticket_routing.service import ticket_routing_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tickets", tags=["ticket-routing"])


@router.post("/routing", response_model=TicketRoutingResponse, response_model_by_alias=True)
def recommend_routing(request: TicketRoutingRequest) -> TicketRoutingResponse:
    try:
        return ticket_routing_service.recommend(request)
    except ProviderError as e:
        logger.error("라우팅 provider 오류: [%s] %s", e.provider, e.message)
        raise HTTPException(status_code=500, detail="라우팅 처리 중 오류가 발생했습니다.")
