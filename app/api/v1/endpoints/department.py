import logging

from fastapi import APIRouter, HTTPException

from app.common.exceptions import ProviderError
from app.domain.department.schemas import RoutingPromptRequest, RoutingPromptResponse
from app.domain.department.service import department_routing_prompt_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/department", tags=["department"])


@router.post("/routing-prompt", response_model=RoutingPromptResponse, response_model_by_alias=True)
def generate_routing_prompt(request: RoutingPromptRequest) -> RoutingPromptResponse:
    try:
        return department_routing_prompt_service.generate(request)
    except ProviderError as e:
        logger.error("부서 routing prompt 생성 오류: [%s] %s", e.provider, e.message)
        raise HTTPException(status_code=500, detail="routing prompt 생성 중 오류가 발생했습니다.")
