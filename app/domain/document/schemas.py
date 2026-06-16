from pydantic import BaseModel, Field


class DocumentPage(BaseModel):
    page: int = Field(gt=0)
    text: str


class DocumentIndexRequest(BaseModel):
    source_id: int = Field(gt=0)
    source_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)  # 파싱 후 주입 — endpoint에서 설정
    pages: list[DocumentPage] | None = None


class DocumentIngestForm(BaseModel):
    source_id: int = Field(gt=0)
    source_type: str = Field(min_length=1)
    title: str = Field(min_length=1)


class DocumentIndexResponse(BaseModel):
    source_id: int
    indexed_chunks: int


class DocumentDeleteResponse(BaseModel):
    source_id: int
    deleted_chunks: int
