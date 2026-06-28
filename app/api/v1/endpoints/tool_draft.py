import logging

from fastapi import APIRouter, HTTPException

from app.common.exceptions import ProviderError
from app.domain.tool_draft.schemas import ToolDraftRequest, ToolDraftResponse
from app.domain.tool_draft.service import tool_draft_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["tool-draft"])


@router.post("/draft", response_model=ToolDraftResponse, response_model_by_alias=True)
def draft_tool(request: ToolDraftRequest) -> ToolDraftResponse:
    try:
        return tool_draft_service.draft(request)
    except ProviderError as e:
        logger.error("Tool 초안 provider 오류: [%s] %s", e.provider, e.message)
        raise HTTPException(status_code=500, detail="Tool 초안 생성 중 오류가 발생했습니다.")
