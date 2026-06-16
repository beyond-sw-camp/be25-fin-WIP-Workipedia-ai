from unittest.mock import MagicMock, patch

import pytest

from app.domain.rag.schemas import RagCandidate, RerankedCandidate


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


def test_search_and_rerank_returns_reranked_list(service):
    from app.core.config import settings

    candidates = _make_candidates(3)
    reranked = _make_reranked(candidates)
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = reranked

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
    ):
        mock_retriever.search.return_value = candidates
        result = service.search_and_rerank("FastAPI 설치", "manual_chunks", rerank_top_k=3)

    assert len(result) == 3
    assert all(isinstance(r, RerankedCandidate) for r in result)
    mock_retriever.search.assert_called_once_with("FastAPI 설치", "manual_chunks")
    mock_reranker.rerank.assert_called_once_with("FastAPI 설치", candidates, 3)


def test_search_and_rerank_returns_empty_when_no_candidates(service):
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
    ):
        mock_retriever.search.return_value = []
        result = service.search_and_rerank("질문", "manual_chunks")

    assert result == []
    mock_reranker.rerank.assert_not_called()


def test_search_and_rerank_skips_reranker_when_retrieval_score_low(service):
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


def test_search_and_rerank_can_use_retrieval_order_when_reranker_disabled(service):
    from app.core.config import settings

    candidates = _make_candidates(4)
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", False),
    ):
        mock_retriever.search.return_value = candidates
        result = service.search_and_rerank("한화비전은 어떤 회사야?", "manual_chunks", rerank_top_k=3)

    assert [r.candidate_id for r in result] == ["MANUAL:1:0", "MANUAL:1:1", "MANUAL:1:2"]
    assert [r.score for r in result] == [0.9, 0.8, 0.7]
    assert [r.retrieval_score for r in result] == [0.9, 0.8, 0.7]
    mock_reranker.rerank.assert_not_called()


def test_search_knowledge_merges_two_collections(service):
    from app.core.config import settings

    kd_candidates = _make_candidates(2, prefix="KNOWLEDGE_DATA")
    mk_candidates = [
        RagCandidate(candidate_id="MANUAL_KNOWLEDGE:2:0", text="수기 지식 A", score=0.85)
    ]
    merged = kd_candidates + mk_candidates
    reranked = _make_reranked(merged)
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = reranked

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", True),
    ):
        mock_retriever.search.side_effect = [kd_candidates, mk_candidates]
        result = service.search_knowledge("지식 질문", rerank_top_k=3)

    assert len(result) == 3
    assert mock_retriever.search.call_count == 2
    mock_reranker.rerank.assert_called_once_with("지식 질문", merged, 3)


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


def test_search_knowledge_skips_reranker_when_merged_top_score_low(service):
    from app.core.config import settings

    kd_candidates = [RagCandidate(candidate_id="KNOWLEDGE_DATA:1:0", text="낮은 관련도", score=0.2)]
    mk_candidates = [RagCandidate(candidate_id="MANUAL_KNOWLEDGE:2:0", text="낮은 관련도", score=0.3)]
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_retrieval_score_threshold", 0.55),
    ):
        mock_retriever.search.side_effect = [kd_candidates, mk_candidates]
        result = service.search_knowledge("사과가 뭐야?")

    assert result == []
    mock_reranker.rerank.assert_not_called()


def test_search_knowledge_can_use_retrieval_order_when_reranker_disabled(service):
    from app.core.config import settings

    kd_candidates = _make_candidates(2, prefix="KNOWLEDGE_DATA")
    mk_candidates = [
        RagCandidate(candidate_id="MANUAL_KNOWLEDGE:2:0", text="수기 지식 A", score=0.85)
    ]
    mock_reranker = MagicMock()

    with (
        patch("app.domain.rag.service.rag_retriever") as mock_retriever,
        patch("app.domain.rag.service.get_reranker", return_value=mock_reranker),
        patch.object(settings, "rag_reranker_enabled", False),
    ):
        mock_retriever.search.side_effect = [kd_candidates, mk_candidates]
        result = service.search_knowledge("지식 질문", rerank_top_k=3)

    assert [r.candidate_id for r in result] == [
        "KNOWLEDGE_DATA:1:0",
        "KNOWLEDGE_DATA:1:1",
        "MANUAL_KNOWLEDGE:2:0",
    ]
    mock_reranker.rerank.assert_not_called()
