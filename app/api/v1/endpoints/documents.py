from fastapi import APIRouter, HTTPException

from app.domain.document.schemas import (
    DocumentDeleteResponse,
    DocumentIndexRequest,
    DocumentIndexResponse,
)
from app.domain.document.service import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest", response_model=DocumentIndexResponse)
def ingest_document(request: DocumentIndexRequest) -> DocumentIndexResponse:
    """
    BE가 추출한 텍스트를 인덱싱한다.

    요청: { source_id, source_type, title, text }
    source_type: MANUAL | WORKI | KNOWLEDGE_DATA | MANUAL_KNOWLEDGE

    에러:
    - 400: 민감정보 마스킹 실패
    - 422: 빈 텍스트 또는 지원하지 않는 source_type
    - 500: 임베딩 실패
    """
    try:
        return document_service.index(request)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/{source_id}", response_model=DocumentDeleteResponse)
def delete_document(source_id: int, source_type: str) -> DocumentDeleteResponse:
    """
    source_id에 해당하는 Qdrant 청크를 전부 삭제한다.

    쿼리 파라미터: source_type (필수)
    에러:
    - 422: 지원하지 않는 source_type
    """
    try:
        return document_service.delete(source_id, source_type)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
