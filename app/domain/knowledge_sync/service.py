import logging

from app.common.exceptions import ProviderError, provider_call
from app.core.config import KNOWLEDGE_SYNC_CONFIG
from app.domain.department.role_keyword_extractor import extract_role_keywords
from app.domain.knowledge_sync.schemas import (
    KnowledgeDeleteResponse,
    KnowledgeSyncRequest,
    KnowledgeSyncResponse,
)
from app.infra.embedding.factory import get_embeddings
from app.infra.vector_store.qdrant_store import qdrant_store


logger = logging.getLogger(__name__)


class KnowledgeSyncService:
    def _build_embedding_document(self, request: KnowledgeSyncRequest) -> str:
        # DEPT_RR(부서 R&R)은 "배정/문의/담당" 보일러플레이트가 라우팅을 쏠리게 하므로,
        # 임베딩 텍스트는 LLM으로 역할 키워드만 추출해 사용한다. (BE/FE 원문은 그대로)
        # 추출 실패 시 원문(content)으로 fallback 해 동기화 자체는 깨지지 않게 한다.
        if request.source_type == "DEPT_RR":
            try:
                keywords = extract_role_keywords(request.content).strip()
                if keywords:
                    return keywords
                logger.warning("DEPT_RR 키워드 추출 결과가 비어 원문으로 임베딩한다. source_id=%s", request.source_id)
            except ProviderError as e:
                logger.warning("DEPT_RR 키워드 추출 실패, 원문으로 임베딩한다. source_id=%s, error=%s",
                               request.source_id, e)
            return request.content
        return f"{request.title}\n{request.content}"

    def sync(self, request: KnowledgeSyncRequest) -> KnowledgeSyncResponse:
        config = KNOWLEDGE_SYNC_CONFIG[request.source_type]
        collection = config["collection"]
        chunk_type = config["type"]

        doc_id = f"{request.source_type}:{request.source_id}"
        point_id = f"{doc_id}:0"
        document = self._build_embedding_document(request)

        with provider_call("embedding"):
            embedding = get_embeddings().embed_query(document)

        metadata = {
            "doc_id": doc_id,
            "source_type": request.source_type,
            "source_id": request.source_id,
            "title": request.title,
            "department_id": request.department_id,
            "department_name": request.department_name,
            "type": chunk_type,
        }

        with provider_call("qdrant"):
            qdrant_store.upsert(
                ids=[point_id],
                documents=[document],
                embeddings=[embedding],
                metadatas=[metadata],
                collection_name=collection,
            )

        return KnowledgeSyncResponse(source_id=request.source_id, synced_chunks=1)

    def delete(self, source_id: int, source_type: str) -> KnowledgeDeleteResponse:
        config = KNOWLEDGE_SYNC_CONFIG[source_type]
        doc_id = f"{source_type}:{source_id}"

        with provider_call("qdrant"):
            deleted = qdrant_store.delete_by_doc_id(doc_id, collection_name=config["collection"])

        return KnowledgeDeleteResponse(source_id=source_id, deleted_chunks=deleted)


knowledge_sync_service = KnowledgeSyncService()
