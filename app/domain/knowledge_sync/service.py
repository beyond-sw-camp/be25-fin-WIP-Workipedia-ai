from app.common.exceptions import ProviderError, provider_call
from app.core.config import KNOWLEDGE_SYNC_CONFIG
from app.domain.knowledge_sync.schemas import (
    KnowledgeDeleteResponse,
    KnowledgeSyncRequest,
    KnowledgeSyncResponse,
)
from app.infra.embedding.factory import get_embeddings
from app.infra.vector_store.qdrant_store import qdrant_store


class KnowledgeSyncService:
    def sync(self, request: KnowledgeSyncRequest) -> KnowledgeSyncResponse:
        config = KNOWLEDGE_SYNC_CONFIG[request.source_type]
        collection = config["collection"]
        chunk_type = config["type"]

        doc_id = f"{request.source_type}:{request.source_id}"
        point_id = f"{doc_id}:0"
        document = f"{request.title}\n{request.content}"

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
