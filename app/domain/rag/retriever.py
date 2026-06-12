from app.common.exceptions import provider_call
from app.core.config import RETRIEVAL_TOP_K
from app.domain.rag.schemas import RagCandidate
from app.infra.embedding.factory import get_embeddings
from app.infra.vector_store.qdrant_store import qdrant_store


class RagRetriever:
    def search(
        self,
        query: str,
        collection_name: str,
        top_k: int = RETRIEVAL_TOP_K,
    ) -> list[RagCandidate]:
        if top_k <= 0:
            return []

        # 질문 텍스트를 벡터로 변환. 실패 시 ProviderError("embedding") 발생
        with provider_call("embedding"):
            embedding = get_embeddings().embed_query(query)

        # 변환된 벡터로 Qdrant에서 유사 문서 top_k개 조회. 미존재 collection은 자동 생성하지 않음
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


rag_retriever = RagRetriever()
