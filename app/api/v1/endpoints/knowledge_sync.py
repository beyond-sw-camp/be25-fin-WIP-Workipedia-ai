import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query

from app.common.exceptions import ProviderError
from app.domain.knowledge_sync.schemas import (
    KnowledgeDeleteResponse,
    KnowledgeSyncRequest,
    KnowledgeSyncResponse,
)
from app.domain.knowledge_sync.service import knowledge_sync_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge-sync"])


@router.post("/sync", response_model=KnowledgeSyncResponse, response_model_by_alias=True)
def sync_knowledge(request: KnowledgeSyncRequest) -> KnowledgeSyncResponse:
    try:
        return knowledge_sync_service.sync(request)
    except ProviderError as e:
        logger.error("지식 동기화 오류: [%s] %s", e.provider, e.message)
        raise HTTPException(status_code=500, detail="지식 동기화 중 오류가 발생했습니다.")


@router.delete("/{source_id}", response_model=KnowledgeDeleteResponse, response_model_by_alias=True)
def delete_knowledge(
    source_id: int = Path(gt=0),
    source_type: Literal["DEPT_RR", "ROUTING_CASE"] = Query(..., alias="sourceType"),
) -> KnowledgeDeleteResponse:
    try:
        return knowledge_sync_service.delete(source_id, source_type)
    except ProviderError as e:
        logger.error("지식 삭제 오류: [%s] %s", e.provider, e.message)
        raise HTTPException(status_code=500, detail="지식 삭제 중 오류가 발생했습니다.")
