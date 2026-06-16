import logging

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
    if top_score < threshold:
        logger.warning(
            "[%s] retrieval_gate=SKIP top_score=%.4f threshold=%.4f",
            collection_name,
            top_score,
            threshold,
        )
        return False
    logger.warning(
        "[%s] retrieval_gate=PASS top_score=%.4f threshold=%.4f",
        collection_name,
        top_score,
        threshold,
    )
    return True


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
        logger.warning("[%s] retrieval_count=%d", collection_name, len(candidates))
        if not candidates:
            return []
        logger.warning(
            "[%s] retrieval_top3=%s",
            collection_name,
            [
                {
                    "rank": idx + 1,
                    "score": round(candidate.score, 4),
                    "id": candidate.candidate_id,
                    "text": _preview(candidate.text),
                }
                for idx, candidate in enumerate(candidates[:3])
            ],
        )
        if not _passes_retrieval_gate(collection_name, candidates):
            return []

        if not settings.rag_reranker_enabled:
            logger.warning("[%s] reranker=DISABLED using retrieval_top%d", collection_name, rerank_top_k)
            return _from_retrieval(candidates, rerank_top_k)

        # 2단계: Cross-Encoder로 후보 재정렬 후 상위 rerank_top_k개 반환
        reranked = get_reranker().rerank(query, candidates, rerank_top_k)
        if reranked:
            logger.warning(
                "[%s] rerank_top3=%s",
                collection_name,
                [
                    {
                        "rank": candidate.rank,
                        "rerank_score": round(candidate.score, 4),
                        "retrieval_score": round(candidate.retrieval_score, 4),
                        "id": candidate.candidate_id,
                        "text": _preview(candidate.text),
                    }
                    for candidate in reranked[:3]
                ],
            )
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
        logger.warning(
            "[knowledge] retrieval_counts=%s",
            {
                COLLECTION_MAP["KNOWLEDGE_DATA"]: len(kd),
                COLLECTION_MAP["MANUAL_KNOWLEDGE"]: len(mk),
            },
        )
        for collection_name, candidates in (
            (COLLECTION_MAP["KNOWLEDGE_DATA"], kd),
            (COLLECTION_MAP["MANUAL_KNOWLEDGE"], mk),
        ):
            if candidates:
                logger.warning(
                    "[%s] retrieval_top3=%s",
                    collection_name,
                    [
                        {
                            "rank": idx + 1,
                            "score": round(candidate.score, 4),
                            "id": candidate.candidate_id,
                            "text": _preview(candidate.text),
                        }
                        for idx, candidate in enumerate(candidates[:3])
                    ],
                )
        if not merged:
            return []
        if not _passes_retrieval_gate("knowledge", merged):
            return []

        if not settings.rag_reranker_enabled:
            logger.warning("[knowledge] reranker=DISABLED using retrieval_top%d", rerank_top_k)
            return _from_retrieval(merged, rerank_top_k)

        reranked = get_reranker().rerank(query, merged, rerank_top_k)
        if reranked:
            logger.warning(
                "[knowledge] rerank_top3=%s",
                [
                    {
                        "rank": candidate.rank,
                        "rerank_score": round(candidate.score, 4),
                        "retrieval_score": round(candidate.retrieval_score, 4),
                        "id": candidate.candidate_id,
                        "text": _preview(candidate.text),
                    }
                    for candidate in reranked[:3]
                ],
            )
        return reranked
