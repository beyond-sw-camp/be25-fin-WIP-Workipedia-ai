from unittest.mock import patch

import pytest

from app.domain.rag.schemas import RagCandidate, RerankedCandidate
from app.domain.ticket_routing.schemas import TicketRoutingRequest, TicketRoutingResponse


@pytest.fixture
def service():
    from app.domain.ticket_routing.service import TicketRoutingService
    return TicketRoutingService()


def _make_rr_candidate(dept_id: int, dept_name: str, score: float) -> RagCandidate:
    return RagCandidate(
        candidate_id=f"ROUTING_RR:{dept_id}:0",
        text=f"{dept_name}은 ERP를 담당한다",
        score=score,
        metadata={"department_id": dept_id, "department_name": dept_name, "type": "rr"},
    )


def _make_case_candidate(dept_id: int, dept_name: str, score: float) -> RagCandidate:
    return RagCandidate(
        candidate_id=f"ROUTING_CASE:{dept_id}:0",
        text="ERP 계정 문제를 해결했다",
        score=score,
        metadata={"department_id": dept_id, "department_name": dept_name, "type": "case"},
    )


def _make_reranked(dept_id: int, dept_name: str, score: float, rank: int) -> RerankedCandidate:
    return RerankedCandidate(
        candidate_id=f"department-{dept_id}",
        text="context",
        score=score,
        rank=rank,
        metadata={"department_id": dept_id, "department_name": dept_name},
    )


def test_recommend_returns_auto_assigned_when_scores_pass(service):
    request = TicketRoutingRequest(title="ERP 접근 불가", content="ERP 로그인이 안 됩니다")

    rr_results = [
        _make_rr_candidate(1, "개발1팀", 0.9),
        _make_rr_candidate(2, "개발2팀", 0.7),
    ]
    case_results = [_make_case_candidate(1, "개발1팀", 0.85)]
    reranked = [
        _make_reranked(1, "개발1팀", 5.5, 1),
        _make_reranked(2, "개발2팀", 3.0, 2),
    ]

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
        patch("app.domain.ticket_routing.service.get_reranker") as mock_reranker_fn,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, case_results]
        mock_reranker_fn.return_value.rerank.return_value = reranked

        result = service.recommend(request)

    assert isinstance(result, TicketRoutingResponse)
    assert result.decision == "AUTO_ASSIGNED"
    assert result.assigned_department_id == 1
    assert result.assigned_department_name == "개발1팀"
    assert result.confidence_score == pytest.approx(5.5)
    assert result.score_margin == pytest.approx(2.5)
    assert len(result.candidate_departments) == 2


def test_recommend_returns_common_queue_when_no_results(service):
    request = TicketRoutingRequest(title="질문", content="내용")

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.return_value = []

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert result.assigned_department_id is None
    assert result.candidate_departments == []


def test_recommend_returns_common_queue_when_single_candidate(service):
    request = TicketRoutingRequest(title="질문", content="내용")

    rr_results = [_make_rr_candidate(1, "개발1팀", 0.9)]
    reranked = [_make_reranked(1, "개발1팀", 5.0, 1)]

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
        patch("app.domain.ticket_routing.service.get_reranker") as mock_reranker_fn,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]
        mock_reranker_fn.return_value.rerank.return_value = reranked

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert "1개" in result.reasons[0]


def test_recommend_returns_common_queue_when_margin_too_small(service):
    request = TicketRoutingRequest(title="질문", content="내용")

    rr_results = [
        _make_rr_candidate(1, "개발1팀", 0.9),
        _make_rr_candidate(2, "개발2팀", 0.85),
    ]
    reranked = [
        _make_reranked(1, "개발1팀", 3.0, 1),
        _make_reranked(2, "개발2팀", 2.8, 2),  # margin = 0.2 < 0.5
    ]

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
        patch("app.domain.ticket_routing.service.get_reranker") as mock_reranker_fn,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]
        mock_reranker_fn.return_value.rerank.return_value = reranked

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"


def test_recommend_skips_candidates_without_department_id(service):
    request = TicketRoutingRequest(title="질문", content="내용")

    rr_results = [
        RagCandidate(candidate_id="bad:0", text="metadata 없음", score=0.9, metadata={}),
    ]

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert result.candidate_departments == []


def test_recommend_returns_common_queue_on_reranker_failure(service):
    from app.common.exceptions import ProviderError

    request = TicketRoutingRequest(title="질문", content="내용")
    rr_results = [
        _make_rr_candidate(1, "개발1팀", 0.9),
        _make_rr_candidate(2, "개발2팀", 0.7),
    ]

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
        patch("app.domain.ticket_routing.service.get_reranker") as mock_reranker_fn,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]
        mock_reranker_fn.return_value.rerank.side_effect = ProviderError("cross-encoder", "모델 오류")

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert result.candidate_departments == []
