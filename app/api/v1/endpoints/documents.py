from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.domain.document.parser.factory import parse_upload_file
from app.domain.document.schemas import (
    DocumentDeleteResponse,
    DocumentIndexRequest,
    DocumentIndexResponse,
)
from app.domain.document.service import document_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest", response_model=DocumentIndexResponse)
def ingest_document(
    source_id: int = Form(..., gt=0),
    source_type: str = Form(..., min_length=1, examples=["MANUAL", "WORKI", "KNOWLEDGE_DATA", "MANUAL_KNOWLEDGE"]),
    title: str = Form(..., min_length=1),
    file: UploadFile = File(...),
) -> DocumentIndexResponse:
    """
    BE가 object storage에서 다운받은 파일을 전송하면 AI 서버가 파싱 후 인덱싱한다.

    지원 형식: pdf, docx, txt
    에러:
    - 415: 지원하지 않는 파일 형식
    - 400: 민감정보 마스킹 실패
    - 422: 빈 텍스트 또는 지원하지 않는 source_type
    - 500: 임베딩 실패
    """
    try:
        text = parse_upload_file(file)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"파일 파싱 실패: {e}")

    try:
        return document_service.index(
            DocumentIndexRequest(source_id=source_id, source_type=source_type, title=title, text=text)
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/{source_id}", response_model=DocumentDeleteResponse)
def delete_document(
    source_id: int,
    source_type: str = Query(..., examples=["MANUAL", "WORKI", "KNOWLEDGE_DATA", "MANUAL_KNOWLEDGE"]),
) -> DocumentDeleteResponse:
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
