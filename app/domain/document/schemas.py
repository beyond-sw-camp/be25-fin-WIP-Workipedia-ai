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


class PageDocumentItem(BaseModel):
    """BE가 페이지 단위로 전달하는 원본 파일/페이지 메타데이터.

    page_number는 원본 PDF 기준 페이지, global_page_number는 매뉴얼 전체 누적 페이지다.
    """

    file_name: str = Field(min_length=1)
    file_key: str = Field(min_length=1)
    file_sort_order: int = Field(ge=0)
    page_number: int = Field(gt=0)
    global_page_number: int = Field(gt=0)
    text: str


class PageIndexRequest(BaseModel):
    source_id: int = Field(gt=0)
    source_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    pages: list[PageDocumentItem] = Field(min_length=1)


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
