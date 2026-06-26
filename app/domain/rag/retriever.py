import logging
import time

from app.common.exceptions import provider_call
from app.common.request_context import get_request_id
from app.core.config import RETRIEVAL_TOP_K, settings
from app.domain.rag.schemas import RagCandidate
from app.infra.embedding.factory import get_embeddings
from app.infra.vector_store.qdrant_store import qdrant_store

logger = logging.getLogger(__name__)


class RagRetriever:
    def search_by_embedding(
        self,
        embedding: list[float],
        collection_name: str,
        top_k: int = RETRIEVAL_TOP_K,
    ) -> list[RagCandidate]:
        if top_k <= 0:
            return []

        t0 = time.perf_counter()
        with provider_call("qdrant"):
            result = qdrant_store.query(
                query_embedding=embedding,
                top_k=top_k,
                collection_name=collection_name,
            )
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s collection=%s qdrant_ms=%.1f retrieved=%d",
                get_request_id(), collection_name, (time.perf_counter() - t0) * 1000, len(result.ids))

        return [
            RagCandidate(
                candidate_id=cid,
                text=text,
                score=score,
                metadata=meta,
            )
            for cid, text, score, meta in zip(
                result.ids, result.documents, result.distances, result.metadatas
            )
        ]

    def search(
        self,
        query: str,
        collection_name: str,
        top_k: int = RETRIEVAL_TOP_K,
    ) -> list[RagCandidate]:
        if top_k <= 0:
            return []

        t0 = time.perf_counter()
        with provider_call("embedding"):
            embedding = get_embeddings().embed_query(query)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s embedding_provider=%s embedding_ms=%.1f",
                get_request_id(), settings.embedding_provider.value, (time.perf_counter() - t0) * 1000)

        return self.search_by_embedding(embedding, collection_name, top_k)


rag_retriever = RagRetriever()
