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


def _doc_key(candidate: RagCandidate) -> str:
    """후보의 소속 문서 식별자(source_type:source_id)를 돌려준다.

    논리 chunk ID는 `{source_type}:{source_id}:{chunk_index}` 형식이므로 앞 두 조각이
    문서를 가리킨다. 형식이 어긋나면 candidate_id 전체를 키로 써 캡이 깨지지 않게 한다.
    """
    parts = candidate.candidate_id.split(":", 2)
    return f"{parts[0]}:{parts[1]}" if len(parts) > 1 else candidate.candidate_id


def _cap_per_document(candidates: list[RagCandidate], max_per_doc: int) -> list[RagCandidate]:
    """문서(source_id)당 점수 상위 max_per_doc개만 남긴다.

    한 문서가 잘게 쪼개져 후보 풀을 도배하면 다른 문서·출처가 근거에 들어올 자리를 잃고,
    조건부 reranking의 '경합' 판단도 가짜로 부풀려진다. 점수 내림차순으로 훑으며 문서별
    카운트가 상한에 닿으면 이후 청크는 버린다. 0이면 캡을 적용하지 않는다.
    """
    if max_per_doc <= 0:
        return candidates
    by_doc: dict[str, list[RagCandidate]] = {}
    for candidate in candidates:
        by_doc.setdefault(_doc_key(candidate), []).append(candidate)
    keep_ids: set[str] = set()
    for group in by_doc.values():
        for candidate in sorted(group, key=lambda c: c.score, reverse=True)[:max_per_doc]:
            keep_ids.add(candidate.candidate_id)
    # 입력 순서를 보존하며 초과 청크만 제거한다(정렬·재배치는 하지 않는다).
    return [candidate for candidate in candidates if candidate.candidate_id in keep_ids]


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

    def _finalize_candidates(
        self,
        query: str,
        candidates: list[RagCandidate],
        rerank_top_k: int,
        collection_label: str,
        per_source_min: int = 0,
    ) -> list[RerankedCandidate]:
        """게이트를 통과한 후보에 후보별 점수 컷과 경합 규모 기반 조건부 reranking을 적용한다.

        1) 후보별 컷: '1위 점수 - margin' 미만 후보는 근거에서 제외한다.
           (게이트는 '1위 점수'만 보므로, 1위만 높고 나머지가 낮은 경우의 노이즈를 여기서 제거한다.)
           절대 임계치가 아니라 1위 대비 상대 거리로 컷한다 — e5처럼 코사인이 좁은 띠에
           몰리는 임베딩에서 절대값 컷은 무력하기 때문이다.
        2) 문서별 캡: 같은 문서(source_id)의 청크는 점수 상위 N개만 남긴다. 한 문서가
           쪼개져 후보 풀을 도배하면 다른 출처가 들어올 자리를 잃고, 아래 경합 판단도
           가짜로 부풀려진다(한 문서 쪼개짐 ≠ 다출처 경합).
        3) 조건부 rerank: 컷·캡 이후 후보 수가 최종 보관 수(rerank_top_k)보다 많을 때만
           Cross-Encoder를 호출한다. 후보가 그 이하면 재정렬해도 버릴 후보가 없어
           순위를 바꿀 실익이 작으므로, 검색(코사인) 순서를 그대로 써 비용을 아낀다.
           코퍼스가 커져 경합 후보가 늘면 reranker가 자동으로 활성화된다.
        `rag_reranker_enabled`는 어떤 상황에서도 reranker를 끄는 마스터 스위치다.
        """
        top_score = max(candidate.score for candidate in candidates)
        floor = top_score - settings.rag_candidate_score_margin
        survivors = [candidate for candidate in candidates if candidate.score >= floor]
        cut_count = len(candidates) - len(survivors)
        before_cap = len(survivors)
        survivors = _cap_per_document(survivors, settings.rag_max_chunks_per_doc)
        capped_count = before_cap - len(survivors)
        if not survivors:
            return []

        use_reranker = settings.rag_reranker_enabled and len(survivors) > rerank_top_k
        if not use_reranker:
            reason = "DISABLED" if not settings.rag_reranker_enabled else "LOW_COMPETITION"
            if settings.latency_log_enabled:
                logger.info("[latency] request_id=%s collection=%s reranker=SKIP(%s) survivors=%d cut=%d capped=%d keep=%d",
                    get_request_id(), collection_label, reason, len(survivors), cut_count, capped_count, rerank_top_k)
            ranked = _from_retrieval(sorted(survivors, key=lambda c: c.score, reverse=True), len(survivors))
            return _select_with_source_quota(ranked, rerank_top_k, per_source_min)

        # 경합 후보가 보관 수보다 많을 때만 Cross-Encoder로 통합 재정렬한다.
        _rerank_start = time.perf_counter()
        reranked = get_reranker().rerank(query, survivors, len(survivors))
        final = _select_with_source_quota(reranked, rerank_top_k, per_source_min)
        if settings.latency_log_enabled:
            logger.info("[latency] request_id=%s collection=%s reranker=ON survivors=%d cut=%d capped=%d keep=%d rerank_ms=%.1f top3=%s",
                get_request_id(), collection_label, len(survivors), cut_count, capped_count, rerank_top_k,
                (time.perf_counter() - _rerank_start) * 1000,
                [{"rank": c.rank, "rerank_score": round(c.score, 4), "retrieval_score": round(c.retrieval_score, 4), "text": _preview(c.text)} for c in final[:3]])
        return final

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

        # 2단계: 후보별 컷 + 경합 규모 기반 조건부 reranking
        return self._finalize_candidates(query, candidates, rerank_top_k, collection_name)

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

        # 후보별 컷 + 경합 규모 기반 조건부 reranking. 출처별 최소 노출 보장을 함께 적용한다.
        return self._finalize_candidates(query, merged, rerank_top_k, "evidence", RERANK_PER_SOURCE_MIN)

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

        # 후보별 컷 + 경합 규모 기반 조건부 reranking
        return self._finalize_candidates(query, merged, rerank_top_k, "knowledge")
