import logging
import time

from app.common.exceptions import ProviderError, WorkipediaException
from app.core.config import CHUNK_CONFIG, COLLECTION_MAP, settings
from app.domain.document.chunker import chunk_text
from app.domain.document.schemas import (
    DocumentDeleteResponse,
    DocumentIndexRequest,
    DocumentIndexResponse,
    PageIndexRequest,
)
from app.infra.embedding.factory import embed_texts
from app.infra.vector_store.qdrant_store import qdrant_store

logger = logging.getLogger(__name__)


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

    def _chunk_file_pages(
        self,
        pages,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[dict]:
        """원본 파일/페이지 메타데이터를 보존하며 파일 단위로 청킹한다.

        한 파일 안에서는 페이지 텍스트를 이어 붙여 chunk_size 기준으로 자르므로,
        짧은 페이지는 합쳐지고 긴 페이지는 쪼개진다. 청크가 여러 페이지에 걸치면
        page_start..page_end 범위로 저장한다. chunk는 파일 경계를 넘지 않는다.
        page_start/page_end는 원본 PDF 기준, global_page_*는 매뉴얼 전체 기준이다.
        """
        chunks: list[dict] = []
        for file_pages in self._group_pages_by_file(pages):
            chunks.extend(self._chunk_single_file(file_pages, chunk_size, chunk_overlap))
        return chunks

    @staticmethod
    def _group_pages_by_file(pages) -> list[list]:
        """연속된 같은 file_key 페이지를 한 파일 그룹으로 묶는다. (BE가 파일·페이지 순으로 정렬해 전달)"""
        groups: list[list] = []
        for page in pages:
            if groups and groups[-1][0].file_key == page.file_key:
                groups[-1].append(page)
            else:
                groups.append([page])
        return groups

    def _chunk_single_file(self, file_pages, chunk_size: int, chunk_overlap: int) -> list[dict]:
        page_separator = "\n"
        full_text = ""
        # (start_offset, end_offset, page) — 연결된 파일 텍스트 내 각 페이지의 문자 범위
        page_spans: list[tuple[int, int, object]] = []
        for page in file_pages:
            page_text = page.text.strip()
            if not page_text:
                continue
            if full_text:
                full_text += page_separator
            start = len(full_text)
            full_text += page_text
            page_spans.append((start, len(full_text), page))

        if not full_text or not page_spans:
            return []

        chunks: list[dict] = []
        search_from = 0
        for raw_chunk in chunk_text(full_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
            chunk = raw_chunk.strip()
            if not chunk:
                continue
            # 연결 텍스트에서 청크 위치를 찾아 어떤 페이지에 걸치는지 역매핑한다.
            pos = full_text.find(chunk, search_from)
            if pos == -1:
                pos = full_text.find(chunk)
            if pos == -1:
                covered = [span[2] for span in page_spans]
                chunk_start, chunk_end = page_spans[0][0], page_spans[-1][1]
            else:
                chunk_start, chunk_end = pos, pos + len(chunk)
                search_from = pos + max(1, len(chunk) - chunk_overlap)
                covered = [pg for (s, e, pg) in page_spans if s < chunk_end and e > chunk_start]
                if not covered:
                    covered = [page_spans[0][2]]

            first = covered[0]
            chunks.append({
                "text": chunk,
                "file_name": first.file_name,
                "file_key": first.file_key,
                "file_sort_order": first.file_sort_order,
                "page_start": min(pg.page_number for pg in covered),
                "page_end": max(pg.page_number for pg in covered),
                "global_page_start": min(pg.global_page_number for pg in covered),
                "global_page_end": max(pg.global_page_number for pg in covered),
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
        total_start = time.perf_counter()
        collection_name = self._resolve_collection(request.source_type)
        doc_id = f"{request.source_type}:{request.source_id}"  # 예: "MANUAL:123"

        # 공백만 있는 텍스트는 청킹/임베딩 의미 없음
        if not request.text.strip():
            raise ValueError("텍스트가 비어 있습니다.")

        # source_type별 청킹 파라미터 적용 (MANUAL·MANUAL_KNOWLEDGE은 길게, WORKI는 짧게)
        chunk_kwargs = CHUNK_CONFIG.get(request.source_type, {})
        chunk_start = time.perf_counter()
        if request.pages:
            page_chunks = self._chunk_pages(request.pages, **chunk_kwargs)
            chunks = [chunk["text"] for chunk in page_chunks]
        else:
            page_chunks = []
            chunks = chunk_text(request.text, **chunk_kwargs)
        chunk_ms = (time.perf_counter() - chunk_start) * 1000
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
            embed_start = time.perf_counter()
            embeddings = embed_texts(chunks)
            embed_ms = (time.perf_counter() - embed_start) * 1000
        except ProviderError as e:
            raise WorkipediaException(status_code=500, message=f"임베딩 실패: {e}") from e

        # 임베딩 성공 후 기존 청크 삭제 (재인덱싱 시 구버전 청크가 검색에 섞이는 것 방지)
        delete_start = time.perf_counter()
        qdrant_store.delete_by_doc_id(doc_id, collection_name=collection_name)
        delete_ms = (time.perf_counter() - delete_start) * 1000

        # 새 청크 저장
        upsert_start = time.perf_counter()
        qdrant_store.upsert(
            ids=chunk_ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            collection_name=collection_name,
        )
        upsert_ms = (time.perf_counter() - upsert_start) * 1000
        total_ms = (time.perf_counter() - total_start) * 1000

        if settings.latency_log_enabled:
            logger.info(
                "[latency] document_index source_type=%s source_id=%s collection=%s "
                "pages=%d chars=%d chunks=%d provider=%s chunk_ms=%.1f embed_ms=%.1f "
                "delete_ms=%.1f upsert_ms=%.1f total_ms=%.1f",
                request.source_type,
                request.source_id,
                collection_name,
                len(request.pages or []),
                len(request.text),
                len(chunks),
                settings.embedding_provider.value,
                chunk_ms,
                embed_ms,
                delete_ms,
                upsert_ms,
                total_ms,
            )

        return DocumentIndexResponse(source_id=request.source_id, indexed_chunks=len(chunks))

    def index_pages(self, request: PageIndexRequest) -> DocumentIndexResponse:
        """BE가 파일/페이지 메타데이터와 함께 전달한 페이지들을 인덱싱한다.

        index()와 달리 chunk마다 원본 파일명·파일키·페이지 번호를 Qdrant payload에 저장해
        챗봇 답변 citation에서 "파일명 / N페이지"를 표시할 수 있게 한다.

        Raises:
            ValueError: 지원하지 않는 source_type
            WorkipediaException(422): 청킹 결과 없음
            WorkipediaException(500): 임베딩 실패 (ProviderError)
        """
        total_start = time.perf_counter()
        collection_name = self._resolve_collection(request.source_type)
        doc_id = f"{request.source_type}:{request.source_id}"

        chunk_kwargs = CHUNK_CONFIG.get(request.source_type, {})
        page_chunks = self._chunk_file_pages(request.pages, **chunk_kwargs)
        chunks = [chunk["text"] for chunk in page_chunks]
        if not chunks:
            raise WorkipediaException(status_code=422, message="청킹 결과가 없습니다.")

        chunk_ids = [f"{doc_id}:{i}" for i in range(len(chunks))]
        metadatas = []
        for i, page_chunk in enumerate(page_chunks):
            metadatas.append({
                "doc_id": doc_id,
                "source_type": request.source_type,
                "source_id": request.source_id,
                "title": request.title,
                "chunk_index": i,
                "file_name": page_chunk["file_name"],
                "file_key": page_chunk["file_key"],
                "file_sort_order": page_chunk["file_sort_order"],
                "page_start": page_chunk["page_start"],
                "page_end": page_chunk["page_end"],
                "global_page_start": page_chunk["global_page_start"],
                "global_page_end": page_chunk["global_page_end"],
            })

        # 임베딩 먼저 시도 — 실패하면 기존 청크를 그대로 유지하고 500 반환
        try:
            embeddings = embed_texts(chunks)
        except ProviderError as e:
            raise WorkipediaException(status_code=500, message=f"임베딩 실패: {e}") from e

        qdrant_store.delete_by_doc_id(doc_id, collection_name=collection_name)
        qdrant_store.upsert(
            ids=chunk_ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            collection_name=collection_name,
        )

        if settings.latency_log_enabled:
            logger.info(
                "[latency] document_index_pages source_type=%s source_id=%s collection=%s "
                "pages=%d chunks=%d total_ms=%.1f",
                request.source_type,
                request.source_id,
                collection_name,
                len(request.pages),
                len(chunks),
                (time.perf_counter() - total_start) * 1000,
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
