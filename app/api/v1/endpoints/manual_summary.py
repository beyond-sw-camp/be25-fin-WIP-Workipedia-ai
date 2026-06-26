import logging

from fastapi import APIRouter, HTTPException

from app.common.exceptions import ProviderError
from app.domain.manual_summary.schemas import (
    ManualChangeSummaryRequest,
    ManualChangeSummaryResponse,
)
from app.domain.manual_summary.service import manual_summary_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/manual", tags=["manual-change-summary"])


@router.post("/change-summary", response_model=ManualChangeSummaryResponse, response_model_by_alias=True)
def change_summary(request: ManualChangeSummaryRequest) -> ManualChangeSummaryResponse:
    try:
        return manual_summary_service.summarize(request)
    except ProviderError as e:
        logger.error("매뉴얼 변경 요약 provider 오류: [%s] %s", e.provider, e.message)
        raise HTTPException(status_code=500, detail="매뉴얼 변경 요약 처리 중 오류가 발생했습니다.")
