from unittest.mock import patch

import pytest

from app.domain.rag.schemas import RagCandidate
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


def test_recommend_returns_common_queue_with_embedding_candidates(service):
    request = TicketRoutingRequest(title="ERP 접근 불가", content="ERP 로그인이 안 됩니다")

    rr_results = [
        _make_rr_candidate(1, "개발1팀", 0.9),
        _make_rr_candidate(2, "개발2팀", 0.7),
    ]
    case_results = [_make_case_candidate(1, "개발1팀", 0.85)]

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, case_results]

        result = service.recommend(request)

    assert isinstance(result, TicketRoutingResponse)
    assert result.decision == "COMMON_QUEUE"
    assert result.assigned_department_id is None
    assert result.assigned_department_name is None
    assert result.confidence_score == pytest.approx(0.9)
    assert result.score_margin == pytest.approx(0.2)
    assert len(result.candidate_departments) == 2
    assert result.candidate_departments[0].department_id == 1
    assert result.model == "embedding-similarity"
    assert result.provider == "qdrant"


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

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert "1개" in result.reasons[0]


def test_recommend_returns_candidates_sorted_by_embedding_score(service):
    request = TicketRoutingRequest(title="질문", content="내용")

    rr_results = [
        _make_rr_candidate(1, "개발1팀", 0.7),
        _make_rr_candidate(2, "개발2팀", 0.85),
    ]

    with (
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert [c.department_id for c in result.candidate_departments] == [2, 1]


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

