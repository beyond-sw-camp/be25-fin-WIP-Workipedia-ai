import logging
import time

from app.common.request_context import get_request_id
from app.core.config import COLLECTION_MAP, RERANK_TOP_K, settings
from app.domain.rag.reranker.cross_encoder_reranker import get_reranker
from app.domain.rag.retriever import rag_retriever
from app.domain.rag.schemas import RagCandidate, RerankedCandidate

logger = logging.getLogger(__name__)


def _preview(text: str, limit: int = 80) -> str:
    return text.replace("\n", " ")[:limit]


def _passes_retrieval_gate(collection_name: str, candidates) -> bool:
    top_score = max((candidate.score for candidate in candidates), default=None)
    threshold = settings.rag_retrieval_score_threshold
    if top_score is None:
        return False
    gate = "PASS" if top_score >= threshold else "SKIP"
    logger.info("[latency] request_id=%s collection=%s retrieval_gate=%s top_score=%.4f threshold=%.4f",
        get_request_id(), collection_name, gate, top_score, threshold)
    return top_score >= threshold


def _from_retrieval(candidates: list[RagCandidate], top_k: int) -> list[RerankedCandidate]:
    return [
        RerankedCandidate(
            candidate_id=candidate.candidate_id,
            text=candidate.text,
            score=candidate.score,
            rank=idx + 1,
            metadata=candidate.metadata,
            retrieval_score=candidate.score,
        )
        for idx, candidate in enumerate(candidates[:top_k])
    ]


class RagService:
    def __init__(self) -> None:
        self.last_retrieval_top_score: float | None = None
        self.last_retrieval_candidate_count = 0

    def search_and_rerank(
        self,
        query: str,
        collection_name: str,
        rerank_top_k: int = RERANK_TOP_K,
    ) -> list[RerankedCandidate]:
        # 1단계: 벡터 유사도로 후보 넓게 검색
        candidates = rag_retriever.search(query, collection_name)
        self.last_retrieval_candidate_count = len(candidates)
        self.last_retrieval_top_score = max((candidate.score for candidate in candidates), default=None)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s collection=%s retrieval_count=%d top3=%s",
                get_request_id(), collection_name, len(candidates),
                [{"rank": i+1, "score": round(c.score, 4), "text": _preview(c.text)} for i, c in enumerate(candidates[:3])])
        if not candidates:
            return []
        if not _passes_retrieval_gate(collection_name, candidates):
            return []

        if not settings.rag_reranker_enabled:
            logger.info("[latency] request_id=%s collection=%s reranker=DISABLED", get_request_id(), collection_name)
            return _from_retrieval(candidates, rerank_top_k)

        # 2단계: Cross-Encoder로 후보 재정렬 후 상위 rerank_top_k개 반환
        _rerank_start = time.perf_counter()
        reranked = get_reranker().rerank(query, candidates, rerank_top_k)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s collection=%s rerank_input=%d rerank_output=%d rerank_ms=%.1f top3=%s",
                get_request_id(), collection_name, len(candidates), len(reranked), (time.perf_counter() - _rerank_start) * 1000,
                [{"rank": c.rank, "rerank_score": round(c.score, 4), "retrieval_score": round(c.retrieval_score, 4), "text": _preview(c.text)} for c in reranked[:3]])
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
        self.last_retrieval_candidate_count = len(merged)
        self.last_retrieval_top_score = max((candidate.score for candidate in merged), default=None)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s collection=knowledge retrieval_counts=%s",
                get_request_id(), {COLLECTION_MAP["KNOWLEDGE_DATA"]: len(kd), COLLECTION_MAP["MANUAL_KNOWLEDGE"]: len(mk)})
        if not merged:
            return []
        if not _passes_retrieval_gate("knowledge", merged):
            return []

        if not settings.rag_reranker_enabled:
            logger.info("[latency] request_id=%s collection=knowledge reranker=DISABLED", get_request_id())
            return _from_retrieval(merged, rerank_top_k)

        _rerank_start = time.perf_counter()
        reranked = get_reranker().rerank(query, merged, rerank_top_k)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s collection=knowledge rerank_input=%d rerank_output=%d rerank_ms=%.1f top3=%s",
                get_request_id(), len(merged), len(reranked), (time.perf_counter() - _rerank_start) * 1000,
                [{"rank": c.rank, "rerank_score": round(c.score, 4), "retrieval_score": round(c.retrieval_score, 4), "text": _preview(c.text)} for c in reranked[:3]])
        return reranked
