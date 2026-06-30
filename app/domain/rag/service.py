import logging
import time

from app.common.exceptions import provider_call
from app.common.request_context import get_request_id
from app.core.config import COLLECTION_MAP, RERANK_PER_SOURCE_MIN, RERANK_TOP_K, settings
from app.domain.rag.reranker.cross_encoder_reranker import get_reranker
from app.domain.rag.retriever import rag_retriever
from app.domain.rag.schemas import RagCandidate, RerankedCandidate
from app.infra.embedding.factory import get_embeddings

# 근거 통합(A+B+C) 대상 collection: 매뉴얼, 워키, 지식화 게시판, 수기 지식
EVIDENCE_COLLECTIONS: list[str] = [
    COLLECTION_MAP["MANUAL"],
    COLLECTION_MAP["WORKI"],
    COLLECTION_MAP["KNOWLEDGE_DATA"],
    COLLECTION_MAP["MANUAL_KNOWLEDGE"],
]

logger = logging.getLogger(__name__)


def _preview(text: str, limit: int = 80) -> str:
    return text.replace("\n", " ")[:limit]


def _log_top_cosine(collection_name: str, candidates: list[RagCandidate]) -> None:
    top = max(candidates, key=lambda candidate: candidate.score, default=None)
    logger.warning(
        "[rag_retrieval] request_id=%s collection=%s candidate_count=%d top_cosine=%s top_candidate_id=%s top_text=%s",
        get_request_id(),
        collection_name,
        len(candidates),
        None if top is None else round(top.score, 4),
        None if top is None else top.candidate_id,
        None if top is None else _preview(top.text),
    )


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


def _select_with_source_quota(
    reranked: list[RerankedCandidate],
    top_k: int,
    per_source_min: int,
) -> list[RerankedCandidate]:
    """통합 reranking 결과에서 출처별 최소 노출을 보장해 최종 후보를 고른다.

    각 source_type별로 '검색(코사인) 점수' 상위 per_source_min개를 먼저 확정한다.
    Cross-Encoder가 특정 출처를 과소평가해도 검색 단계에서 관련 높던 후보가 살아남는다.
    남은 자리는 통합 rerank 순서대로 채우고, 최종은 rerank 점수 내림차순으로 정렬한다.
    """
    if per_source_min <= 0:
        return reranked[:top_k]

    by_source: dict[str | None, list[RerankedCandidate]] = {}
    for candidate in reranked:
        by_source.setdefault(candidate.metadata.get("source_type"), []).append(candidate)

    selected: list[RerankedCandidate] = []
    selected_ids: set[str] = set()
    for candidates in by_source.values():
        # 출처별 보장은 retrieval_score(코사인) 기준 — rerank가 묻은 관련 후보 구제
        for candidate in sorted(candidates, key=lambda c: c.retrieval_score, reverse=True)[:per_source_min]:
            if candidate.candidate_id not in selected_ids:
                selected.append(candidate)
                selected_ids.add(candidate.candidate_id)

    # 남은 자리: 통합 rerank 순서(reranked는 이미 rerank 점수 내림차순)대로 채운다
    final_size = max(top_k, len(selected))
    for candidate in reranked:
        if len(selected) >= final_size:
            break
        if candidate.candidate_id not in selected_ids:
            selected.append(candidate)
            selected_ids.add(candidate.candidate_id)

    selected.sort(key=lambda c: c.score, reverse=True)
    for idx, candidate in enumerate(selected):
        candidate.rank = idx + 1
    return selected


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
        _log_top_cosine(collection_name, candidates)
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

    def search_evidence(
        self,
        query: str,
        rerank_top_k: int = RERANK_TOP_K,
    ) -> list[RerankedCandidate]:
        # 근거 통합 검색: 매뉴얼·워키·지식 collection을 모두 검색해 후보를 합친 뒤
        # 한 번만 통합 reranking한다. 폴백이 아니라 모든 출처를 함께 답변 근거로 쓰기 위함.
        # 질문 임베딩은 1회만 생성해 모든 collection 검색에서 재사용한다.
        _embed_start = time.perf_counter()
        with provider_call("embedding"):
            embedding = get_embeddings().embed_query(query)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s embedding_provider=%s embedding_ms=%.1f (evidence 1회 재사용)",
                get_request_id(), settings.embedding_provider.value, (time.perf_counter() - _embed_start) * 1000)

        merged: list[RagCandidate] = []
        per_counts: dict[str, int] = {}
        for collection_name in EVIDENCE_COLLECTIONS:
            candidates = rag_retriever.search_by_embedding(embedding, collection_name)
            per_counts[collection_name] = len(candidates)
            _log_top_cosine(collection_name, candidates)
            merged += candidates

        self.last_retrieval_candidate_count = len(merged)
        self.last_retrieval_top_score = max((candidate.score for candidate in merged), default=None)
        _log_top_cosine("evidence", merged)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s collection=evidence retrieval_counts=%s",
                get_request_id(), per_counts)
        if not merged:
            return []
        if not _passes_retrieval_gate("evidence", merged):
            return []

        if not settings.rag_reranker_enabled:
            logger.info("[latency] request_id=%s collection=evidence reranker=DISABLED", get_request_id())
            # reranker 비활성 시에도 출처별 보장은 retrieval 순서로 적용한다
            from_retrieval = _from_retrieval(merged, len(merged))
            return _select_with_source_quota(from_retrieval, rerank_top_k, RERANK_PER_SOURCE_MIN)

        # 합친 후보 '전체'를 한 번만 Cross-Encoder로 통합 재정렬한 뒤,
        # 출처별 최소 노출 보장을 적용해 최종 rerank_top_k개를 고른다.
        _rerank_start = time.perf_counter()
        reranked_all = get_reranker().rerank(query, merged, len(merged))
        final = _select_with_source_quota(reranked_all, rerank_top_k, RERANK_PER_SOURCE_MIN)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s collection=evidence rerank_input=%d final=%d per_source_min=%d rerank_ms=%.1f top=%s",
                get_request_id(), len(merged), len(final), RERANK_PER_SOURCE_MIN, (time.perf_counter() - _rerank_start) * 1000,
                [{"rank": c.rank, "src": c.metadata.get("source_type"), "rerank_score": round(c.score, 4), "retrieval_score": round(c.retrieval_score, 4), "text": _preview(c.text)} for c in final])
        return final

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
        _log_top_cosine(COLLECTION_MAP["KNOWLEDGE_DATA"], kd)
        _log_top_cosine(COLLECTION_MAP["MANUAL_KNOWLEDGE"], mk)
        _log_top_cosine("knowledge", merged)
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
