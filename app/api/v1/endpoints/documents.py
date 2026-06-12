from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.domain.document.parser.docx_parser import DocxParser
from app.domain.document.parser.pdf_parser import PdfParser
from app.domain.document.parser.txt_parser import TxtParser
from app.domain.document.schemas import (
    DocumentDeleteResponse,
    DocumentIndexRequest,
    DocumentIndexResponse,
)
from app.domain.document.service import document_service

router = APIRouter(prefix="/documents", tags=["documents"])

_PARSERS = {
    "application/pdf": PdfParser(),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxParser(),
    "text/plain": TxtParser(),
}
_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def _parse_file(file: UploadFile) -> str:
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    content_type = file.content_type or ""

    parser = _PARSERS.get(content_type)
    if parser is None:
        # content_type 없을 때 확장자로 fallback
        ext_map = {".pdf": PdfParser(), ".docx": DocxParser(), ".txt": TxtParser()}
        parser = ext_map.get(ext)

    if parser is None:
        raise HTTPException(status_code=415, detail=f"지원하지 않는 파일 형식입니다. 허용: pdf, docx, txt")

    file_bytes = file.file.read()
    return parser.parse(file_bytes, file.filename or "")


@router.post("/ingest", response_model=DocumentIndexResponse)
def ingest_document(
    source_id: int = Form(..., gt=0),
    source_type: str = Form(..., min_length=1),
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
    text = _parse_file(file)
    try:
        request = DocumentIndexRequest(
            source_id=source_id,
            source_type=source_type,
            title=title,
            text=text,
        )
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
