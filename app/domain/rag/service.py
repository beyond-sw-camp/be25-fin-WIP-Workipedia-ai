import logging

from app.core.config import COLLECTION_MAP, RERANK_TOP_K
from app.domain.rag.reranker.cross_encoder_reranker import get_reranker
from app.domain.rag.retriever import rag_retriever
from app.domain.rag.schemas import RerankedCandidate

logger = logging.getLogger(__name__)


class RagService:
    def search_and_rerank(
        self,
        query: str,
        collection_name: str,
        rerank_top_k: int = RERANK_TOP_K,
    ) -> list[RerankedCandidate]:
        # 1단계: 벡터 유사도로 후보 넓게 검색
        candidates = rag_retriever.search(query, collection_name)
        logger.warning("[%s] 검색 결과: %d개", collection_name, len(candidates))
        if not candidates:
            return []

        # 2단계: Cross-Encoder로 후보 재정렬 후 상위 rerank_top_k개 반환
        reranked = get_reranker().rerank(query, candidates, rerank_top_k)
        if reranked:
            logger.warning("[%s] rerank 1위 점수: %.4f", collection_name, reranked[0].score)
            logger.warning("[%s] top3 텍스트: %s", collection_name, [c.text[:80] for c in reranked[:3]])
        return reranked

    def search_knowledge(
        self,
        query: str,
        rerank_top_k: int = RERANK_TOP_K,
    ) -> list[RerankedCandidate]:
        # C단계: KNOWLEDGE_DATA와 MANUAL_KNOWLEDGE를 각각 검색 후 합산
        # 두 collection을 합친 뒤 통합 reranking해야 공정한 순위 비교가 가능함
        kd = rag_retriever.search(query, COLLECTION_MAP["KNOWLEDGE_DATA"])
        mk = rag_retriever.search(query, COLLECTION_MAP["MANUAL_KNOWLEDGE"])
        merged = kd + mk
        if not merged:
            return []

        return get_reranker().rerank(query, merged, rerank_top_k)
