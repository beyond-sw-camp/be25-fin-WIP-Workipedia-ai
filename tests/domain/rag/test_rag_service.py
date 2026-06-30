from unittest.mock import MagicMock, patch

import pytest

from app.domain.rag.schemas import RagCandidate, RerankedCandidate

# 캡을 사실상 끄는 값(경합 트리거 자체를 검증하는 테스트에서 같은 문서 후보가 잘리지 않게).
NO_CAP = 50


def _make_candidates(n: int, prefix: str = "MANUAL") -> list[RagCandidate]:
    return [
        RagCandidate(candidate_id=f"{prefix}:1:{i}", text=f"문서 {i}", score=0.9 - i * 0.1)
        for i in range(n)
    ]


def _make_reranked(candidates: list[RagCandidate]) -> list[RerankedCandidate]:
    return [
        RerankedCandidate(
            candidate_id=c.candidate_id,
            text=c.text,
            score=0.9 - i * 0.1,
            rank=i + 1,
            metadata=c.metadata,
            retrieval_score=c.score,
        )
        for i, c in enumerate(candidates)
    ]


@pytest.fixture
def service():
    from app.domain.rag.service import RagService
    return RagService()


# ── 조건부 reranking: 경합 후보가 보관 수보다 '많을 때만' reranker 사용 ──────────

def test_uses_reranker_when_survivors_exceed_keep(service):
    """컷·캡 이후 후보 수 > rerank_top_k이면 Cross-Encoder를 호출한다."""
    from app.core.config import settings

    candidates = _make_candidates(5)  # 0.9~0.5
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = _make_reranked(candidates)

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 0.5),  # 0.4 폭 전부 생존
        patch.object(settings, "rag_max_chunks_per_doc", NO_CAP),
    ):
        mock_retriever.search.return_value = candidates
        result = service.search_and_rerank("FastAPI 설치", "manual_chunks", rerank_top_k=3)

    mock_reranker.rerank.assert_called_once_with("FastAPI 설치", candidates, 5)
    assert len(result) == 3
    assert all(isinstance(r, RerankedCandidate) for r in result)


def test_skips_reranker_when_survivors_within_keep(service):
    """컷·캡 이후 후보 수 <= rerank_top_k이면 재정렬 실익이 없어 reranker를 건너뛴다."""
    from app.core.config import settings

    candidates = _make_candidates(3)  # survivors=3 == keep
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 0.5),
        patch.object(settings, "rag_max_chunks_per_doc", NO_CAP),
    ):
        mock_retriever.search.return_value = candidates
        result = service.search_and_rerank("질문", "manual_chunks", rerank_top_k=3)

    mock_reranker.rerank.assert_not_called()
    assert [r.candidate_id for r in result] == ["MANUAL:1:0", "MANUAL:1:1", "MANUAL:1:2"]
    assert [r.score for r in result] == [0.9, 0.8, 0.7]


# ── 후보별 컷: '1위 - margin' 미만 후보는 근거에서 제외(상대 거리 기반) ─────────

def test_cuts_candidates_below_margin(service):
    """1위만 높고 나머지가 1위에서 margin 이상 떨어지면, 그 후보들은 근거에서 빠진다."""
    from app.core.config import settings

    candidates = [
        RagCandidate(candidate_id="MANUAL:1:0", text="관련", score=0.9),
        RagCandidate(candidate_id="MANUAL:1:1", text="관련", score=0.6),
        RagCandidate(candidate_id="MANUAL:1:2", text="노이즈", score=0.3),
        RagCandidate(candidate_id="MANUAL:1:3", text="노이즈", score=0.2),
    ]
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 0.4),  # floor=0.5 → 0.6 생존, 0.3·0.2 컷
        patch.object(settings, "rag_max_chunks_per_doc", NO_CAP),
    ):
        mock_retriever.search.return_value = candidates
        result = service.search_and_rerank("질문", "manual_chunks", rerank_top_k=3)

    assert [r.candidate_id for r in result] == ["MANUAL:1:0", "MANUAL:1:1"]
    mock_reranker.rerank.assert_not_called()


def test_cut_runs_before_reranker(service):
    """컷으로 노이즈를 제거한 뒤, 남은 후보가 많을 때만 reranker가 그 survivors를 받는다."""
    from app.core.config import settings

    candidates = [
        RagCandidate(candidate_id=f"MANUAL:1:{i}", text=f"문서 {i}", score=s)
        for i, s in enumerate([0.9, 0.8, 0.7, 0.6, 0.55, 0.4, 0.3])
    ]
    survivors = candidates[:5]  # floor=0.9-0.35=0.55 → 0.55 이상 5개
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = _make_reranked(survivors)

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 0.35),
        patch.object(settings, "rag_max_chunks_per_doc", NO_CAP),
    ):
        mock_retriever.search.return_value = candidates
        service.search_and_rerank("질문", "manual_chunks", rerank_top_k=3)

    mock_reranker.rerank.assert_called_once_with("질문", survivors, 5)


# ── 문서별 캡: 한 문서가 후보 풀을 도배하지 못하게 source_id당 N개로 제한 ──────────

def test_caps_chunks_per_document(service):
    """같은 문서(source_id)는 점수 상위 N개만 남고, 다른 문서 후보는 보존된다."""
    from app.core.config import settings

    # 한 문서(MANUAL:100)가 5청크, 다른 문서(WORKI:200)가 1청크
    flood = [
        RagCandidate(candidate_id=f"MANUAL:100:{i}", text=f"보수규정 {i}",
                     score=0.88 - i * 0.01, metadata={"source_type": "MANUAL"})
        for i in range(5)
    ]
    other = [RagCandidate(candidate_id="WORKI:200:0", text="워키", score=0.80,
                          metadata={"source_type": "WORKI"})]
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 1.0),  # 컷은 비활성
        patch.object(settings, "rag_max_chunks_per_doc", 3),
    ):
        mock_retriever.search.return_value = flood + other
        result = service.search_and_rerank("퇴직금", "manual_chunks", rerank_top_k=6)

    ids = [r.candidate_id for r in result]
    # MANUAL:100은 점수 상위 3개만, WORKI:200은 보존 → 총 4개, reranker는 미사용(4 <= 6)
    assert ids == ["MANUAL:100:0", "MANUAL:100:1", "MANUAL:100:2", "WORKI:200:0"]
    mock_reranker.rerank.assert_not_called()


def test_cap_turns_intra_doc_flood_into_skip(service):
    """한 문서가 쪼개져 후보가 많아도, 캡 적용 후 keep 이하가 되면 reranker를 건너뛴다."""
    from app.core.config import settings

    # 같은 문서 10청크 → 캡(3) 적용 시 survivors=3 <= keep(6) → SKIP
    flood = [
        RagCandidate(candidate_id=f"MANUAL:100:{i}", text=f"보수규정 {i}", score=0.88 - i * 0.005)
        for i in range(10)
    ]
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 1.0),
        patch.object(settings, "rag_max_chunks_per_doc", 3),
    ):
        mock_retriever.search.return_value = flood
        result = service.search_and_rerank("퇴직금", "manual_chunks", rerank_top_k=6)

    mock_reranker.rerank.assert_not_called()
    assert len(result) == 3


# ── 마스터 스위치 / 빈 결과 / 게이트 ─────────────────────────────────────────

def test_master_switch_off_skips_reranker_even_with_competition(service):
    """rag_reranker_enabled=False이면 경합이 많아도 reranker를 쓰지 않는다."""
    from app.core.config import settings

    candidates = _make_candidates(5)
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", False),
        patch.object(settings, "rag_candidate_score_margin", 0.5),
        patch.object(settings, "rag_max_chunks_per_doc", NO_CAP),
    ):
        mock_retriever.search.return_value = candidates
        result = service.search_and_rerank("질문", "manual_chunks", rerank_top_k=3)

    mock_reranker.rerank.assert_not_called()
    assert [r.score for r in result] == [0.9, 0.8, 0.7]


def test_returns_empty_when_no_candidates(service):
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
    ):
        mock_retriever.search.return_value = []
        result = service.search_and_rerank("질문", "manual_chunks")

    assert result == []
    mock_reranker.rerank.assert_not_called()


def test_returns_empty_when_top_score_below_gate(service):
    from app.core.config import settings

    candidates = [RagCandidate(candidate_id="MANUAL:1:0", text="낮은 관련도", score=0.2)]
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_retrieval_score_threshold", 0.55),
    ):
        mock_retriever.search.return_value = candidates
        result = service.search_and_rerank("사과가 뭐야?", "manual_chunks")

    assert result == []
    mock_reranker.rerank.assert_not_called()


def test_logs_top_cosine(service, caplog):
    candidates = _make_candidates(2)
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        caplog.at_level("INFO", logger="app.domain.rag.service"),
    ):
        mock_retriever.search.return_value = candidates
        service.search_and_rerank("질문", "manual_chunks")

    assert "collection=manual_chunks" in caplog.text
    assert "top_cosine=0.9" in caplog.text
    assert "top_candidate_id=MANUAL:1:0" in caplog.text


# ── 지식 통합 검색(두 collection 합산) ───────────────────────────────────────

def test_search_knowledge_merges_and_reranks_on_competition(service):
    from app.core.config import settings

    # 서로 다른 문서로 구성해 캡(문서당 3)에 걸리지 않게 한다
    kd_candidates = [
        RagCandidate(candidate_id=f"KNOWLEDGE_DATA:{i}:0", text=f"지식 {i}", score=0.9 - i * 0.1)
        for i in range(3)
    ]
    mk_candidates = [
        RagCandidate(candidate_id="MANUAL_KNOWLEDGE:9:0", text="수기 지식 A", score=0.85)
    ]
    merged = kd_candidates + mk_candidates  # 4개 > keep(3)
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = _make_reranked(merged)

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 0.5),
        patch.object(settings, "rag_max_chunks_per_doc", 3),
    ):
        mock_retriever.search.side_effect = [kd_candidates, mk_candidates]
        result = service.search_knowledge("지식 질문", rerank_top_k=3)

    assert mock_retriever.search.call_count == 2
    mock_reranker.rerank.assert_called_once_with("지식 질문", merged, 4)
    assert len(result) == 3


def test_search_knowledge_returns_empty_when_both_collections_empty(service):
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
    ):
        mock_retriever.search.side_effect = [[], []]
        result = service.search_knowledge("질문")

    assert result == []
    mock_reranker.rerank.assert_not_called()


def test_search_knowledge_uses_cosine_order_when_low_competition(service):
    """두 collection 합산 후보가 keep 이하이면 reranker 없이 코사인 내림차순을 쓴다."""
    from app.core.config import settings

    kd_candidates = [
        RagCandidate(candidate_id="KNOWLEDGE_DATA:1:0", text="지식 0", score=0.9),
        RagCandidate(candidate_id="KNOWLEDGE_DATA:2:0", text="지식 1", score=0.8),
    ]
    mk_candidates = [
        RagCandidate(candidate_id="MANUAL_KNOWLEDGE:9:0", text="수기 지식 A", score=0.85)
    ]
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 0.5),
        patch.object(settings, "rag_max_chunks_per_doc", 3),
    ):
        mock_retriever.search.side_effect = [kd_candidates, mk_candidates]
        result = service.search_knowledge("지식 질문", rerank_top_k=3)

    mock_reranker.rerank.assert_not_called()
    # 합산 후 코사인 내림차순: 0.9 > 0.85 > 0.8
    assert [r.candidate_id for r in result] == [
        "KNOWLEDGE_DATA:1:0",
        "MANUAL_KNOWLEDGE:9:0",
        "KNOWLEDGE_DATA:2:0",
    ]


# ── 근거 통합 검색(4개 출처)에서 출처별 보장 ─────────────────────────────────

def test_search_evidence_keeps_source_quota_without_reranker(service):
    """경합이 적어 reranker를 건너뛰어도, 출처별 최소 노출 보장은 유지된다."""
    from app.core.config import settings

    embedding = [0.1, 0.2, 0.3]
    manual = [RagCandidate(candidate_id="MANUAL:1:0", text="매뉴얼", score=0.9,
                           metadata={"source_type": "MANUAL"})]
    worki = [RagCandidate(candidate_id="WORKI:2:0", text="워키", score=0.7,
                          metadata={"source_type": "WORKI"})]
    mock_reranker = MagicMock()
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = embedding

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch("app.domain.rag.service.get_embeddings", return_value=mock_embeddings),
        patch.object(settings, "rag_reranker_enabled", True),
        patch.object(settings, "rag_candidate_score_margin", 0.5),
        patch.object(settings, "rag_max_chunks_per_doc", 3),
    ):
        mock_retriever.search_by_embedding.side_effect = [manual, worki, [], []]
        result = service.search_evidence("질문", rerank_top_k=3)

    mock_reranker.rerank.assert_not_called()
    ids = [r.candidate_id for r in result]
    assert "MANUAL:1:0" in ids and "WORKI:2:0" in ids
