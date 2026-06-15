from app.common.exceptions import provider_call
from app.core.config import RETRIEVAL_TOP_K
from app.domain.rag.schemas import RagCandidate
from app.infra.embedding.factory import get_embeddings
from app.infra.vector_store.qdrant_store import qdrant_store


class RagRetriever:
    def search_by_embedding(
        self,
        embedding: list[float],
        collection_name: str,
        top_k: int = RETRIEVAL_TOP_K,
    ) -> list[RagCandidate]:
        if top_k <= 0:
            return []

        with provider_call("qdrant"):
            result = qdrant_store.query(
                query_embedding=embedding,
                top_k=top_k,
                collection_name=collection_name,
            )

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

        with provider_call("embedding"):
            embedding = get_embeddings().embed_query(query)

        return self.search_by_embedding(embedding, collection_name, top_k)


rag_retriever = RagRetriever()
