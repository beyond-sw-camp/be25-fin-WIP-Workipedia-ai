from fastapi import APIRouter, File, UploadFile

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/pdf")
async def ingest_pdf(file: UploadFile = File(...)):
    # TODO: 청킹 → 임베딩 → ChromaDB 저장
    return {"filename": file.filename, "indexed_chunks": 0}
