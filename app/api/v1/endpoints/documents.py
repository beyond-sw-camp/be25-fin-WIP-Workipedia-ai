from fastapi import APIRouter, File, UploadFile

from app.domain.document.schemas import DocumentIngestResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest", response_model=DocumentIngestResponse)
async def ingest_document(file: UploadFile = File(...)):
    # TODO: DocumentService 연결
    return DocumentIngestResponse(filename=file.filename or "", indexed_chunks=0)
