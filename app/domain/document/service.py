from app.common.exceptions import ProviderError, WorkipediaException
from app.core.config import CHUNK_CONFIG, COLLECTION_MAP
from app.domain.document.chunker import chunk_text
from app.domain.document.schemas import (
    DocumentDeleteResponse,
    DocumentIndexRequest,
    DocumentIndexResponse,
)
from app.infra.embedding.factory import embed_texts
from app.infra.vector_store.qdrant_store import qdrant_store


class DocumentService:
    def _chunk_pages(
        self,
        pages,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[dict]:
        chunks: list[dict] = []

        for page in pages:
            page_text = page.text.strip()
            if not page_text:
                continue
            for chunk in chunk_text(page_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
                if chunk.strip():
                    chunks.append({
                        "text": chunk.strip(),
                        "page_start": page.page,
                        "page_end": page.page,
                    })

        return chunks

    def index(self, request: DocumentIndexRequest) -> DocumentIndexResponse:
        """
        BE가 전달한 텍스트를 마스킹 → 청킹 → 임베딩 → Qdrant 저장한다.
        임베딩 성공 후 기존 청크를 삭제해 임베딩 실패 시 기존 데이터를 보존한다.

        Raises:
            ValueError: 빈 텍스트 또는 지원하지 않는 source_type
            WorkipediaException(400): 민감정보 마스킹 실패 (MaskingBlockedError)
            WorkipediaException(500): 임베딩 실패 (ProviderError)
        """
        # source_type → Qdrant collection 이름, 내부 doc_id 결정
        collection_name = self._resolve_collection(request.source_type)
        doc_id = f"{request.source_type}:{request.source_id}"  # 예: "MANUAL:123"

        # 공백만 있는 텍스트는 청킹/임베딩 의미 없음
        if not request.text.strip():
            raise ValueError("텍스트가 비어 있습니다.")

        # source_type별 청킹 파라미터 적용 (MANUAL·MANUAL_KNOWLEDGE은 길게, WORKI는 짧게)
        chunk_kwargs = CHUNK_CONFIG.get(request.source_type, {})
        if request.pages:
            page_chunks = self._chunk_pages(request.pages, **chunk_kwargs)
            chunks = [chunk["text"] for chunk in page_chunks]
        else:
            page_chunks = []
            chunks = chunk_text(request.text, **chunk_kwargs)
        if not chunks:
            raise WorkipediaException(status_code=422, message="청킹 결과가 없습니다.")

        # 각 청크에 고유 ID와 출처 메타데이터 부여 (RAG 검색 결과에서 출처 표시에 사용)
        chunk_ids = [f"{doc_id}:{i}" for i in range(len(chunks))]
        metadatas = []
        for i in range(len(chunks)):
            metadata = {
                "doc_id": doc_id,
                "source_type": request.source_type,
                "source_id": request.source_id,
                "title": request.title,
                "chunk_index": i,
            }
            if page_chunks:
                metadata["page_start"] = page_chunks[i]["page_start"]
                metadata["page_end"] = page_chunks[i]["page_end"]
            metadatas.append(metadata)

        # 임베딩 먼저 시도 — 실패하면 기존 청크를 그대로 유지하고 500 반환
        try:
            embeddings = embed_texts(chunks)
        except ProviderError as e:
            raise WorkipediaException(status_code=500, message=f"임베딩 실패: {e}") from e

        # 임베딩 성공 후 기존 청크 삭제 (재인덱싱 시 구버전 청크가 검색에 섞이는 것 방지)
        qdrant_store.delete_by_doc_id(doc_id, collection_name=collection_name)

        # 새 청크 저장
        qdrant_store.upsert(
            ids=chunk_ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            collection_name=collection_name,
        )

        return DocumentIndexResponse(source_id=request.source_id, indexed_chunks=len(chunks))

    def delete(self, source_id: int, source_type: str) -> DocumentDeleteResponse:
        """
        source_id + source_type에 해당하는 Qdrant 청크를 전부 삭제한다.
        삭제된 청크 수를 반환한다.

        Raises:
            ValueError: 지원하지 않는 source_type
        """
        collection_name = self._resolve_collection(source_type)
        doc_id = f"{source_type}:{source_id}"
        deleted = qdrant_store.delete_by_doc_id(doc_id, collection_name=collection_name)
        return DocumentDeleteResponse(source_id=source_id, deleted_chunks=deleted)

    def _resolve_collection(self, source_type: str) -> str:
        """source_type을 Qdrant collection 이름으로 변환한다."""
        if source_type not in COLLECTION_MAP:
            raise ValueError(f"지원하지 않는 source_type: {source_type}")
        return COLLECTION_MAP[source_type]


document_service = DocumentService()
