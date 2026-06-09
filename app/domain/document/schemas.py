from pydantic import BaseModel


class DocumentIngestResponse(BaseModel):
    filename: str
    indexed_chunks: int
