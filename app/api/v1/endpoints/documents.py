from typing import Literal

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile

from app.domain.document.parser.factory import parse_upload_file, parse_upload_pages
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
    source_type: Literal["MANUAL"] = Form(...),
    title: str = Form(..., min_length=1),
    files: list[UploadFile] = File(...),
) -> DocumentIndexResponse:
    """
    BE가 object storage에서 다운받은 파일(1개 이상)을 전송하면 AI 서버가 파싱 후 인덱싱한다.
    source_type은 MANUAL만 허용한다. 텍스트 기반 source_type은 /ingest-text를 사용한다.

    지원 형식: pdf, docx, txt
    에러:
    - 415: 지원하지 않는 파일 형식
    - 400: 민감정보 마스킹 실패
    - 422: 빈 텍스트, 빈 파일 목록, 지원하지 않는 source_type
    - 500: 임베딩 실패
    """
    if not files:
        raise HTTPException(status_code=422, detail="files가 비어 있습니다.")

    texts: list[str] = []
    all_pages: list[dict] | None = None

    try:
        for f in files:
            pages = parse_upload_pages(f)
            if pages is None:
                f.file.seek(0)
                texts.append(parse_upload_file(f))
            else:
                texts.append("\n".join(page["text"] for page in pages))
                if all_pages is None:
                    all_pages = []
                all_pages.extend(pages)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"파일 파싱 실패: {e}")

    text = "\n\n".join(texts)

    try:
        return document_service.index(
            DocumentIndexRequest(
                source_id=source_id,
                source_type=source_type,
                title=title,
                text=text,
                pages=all_pages,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/ingest-text", response_model=DocumentIndexResponse)
def ingest_text(
    source_id: int = Body(..., gt=0),
    source_type: Literal["WORKI", "KNOWLEDGE_DATA", "MANUAL_KNOWLEDGE"] = Body(...),
    title: str = Body(..., min_length=1),
    text: str = Body(...),
) -> DocumentIndexResponse:
    """
    텍스트를 직접 전달해 인덱싱한다. WORKI, KNOWLEDGE_DATA, MANUAL_KNOWLEDGE에 사용한다.
    파일 업로드 없이 BE가 직접 텍스트를 전달하는 경로다.

    에러:
    - 422: 빈 텍스트 또는 지원하지 않는 source_type
    - 500: 임베딩 실패
    """
    if not text.strip():
        raise HTTPException(status_code=422, detail="text가 비어 있습니다.")

    try:
        return document_service.index(
            DocumentIndexRequest(
                source_id=source_id,
                source_type=source_type,
                title=title,
                text=text,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.delete("/{source_id}", response_model=DocumentDeleteResponse)
def delete_document(
    source_id: int,
    source_type: Literal["MANUAL"] = Query(...),
) -> DocumentDeleteResponse:
    """
    source_id에 해당하는 Qdrant 청크를 전부 삭제한다. MANUAL source_type만 허용한다.

    쿼리 파라미터: source_type (필수)
    에러:
    - 422: 지원하지 않는 source_type
    """
    try:
        return document_service.delete(source_id, source_type)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
