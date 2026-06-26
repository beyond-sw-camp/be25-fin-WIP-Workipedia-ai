from unittest.mock import patch

import pytest

from app.domain.rag.schemas import RagCandidate, RerankedCandidate
from app.domain.ticket_routing.schemas import TicketRoutingRequest, TicketRoutingResponse


@pytest.fixture
def service():
    from app.domain.ticket_routing.service import TicketRoutingService
    return TicketRoutingService()


def _passthrough(query, candidates, top_k):
    """retrieval 점수를 그대로 보존하는 reranker 대역 (기존 점수 기반 테스트 유지용)."""
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)[:top_k]
    return [
        RerankedCandidate(
            candidate_id=c.candidate_id, text=c.text, score=c.score,
            rank=i + 1, metadata=c.metadata, retrieval_score=c.score,
        )
        for i, c in enumerate(ranked)
    ]


@pytest.fixture(autouse=True)
def _reranker_passthrough():
    # 기본은 pass-through. 변별을 검증하는 테스트만 side_effect를 덮어쓴다.
    with patch("app.domain.ticket_routing.service.get_reranker") as mock_get:
        mock_get.return_value.rerank.side_effect = _passthrough
        yield mock_get


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


def test_recommend_returns_auto_assigned_when_score_and_margin_pass(service):
    request = TicketRoutingRequest(title="ERP 접근 불가", content="ERP 로그인이 안 됩니다")

    rr_results = [
        _make_rr_candidate(1, "개발1팀", 0.9),
        _make_rr_candidate(2, "개발2팀", 0.2),
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
    assert result.decision == "AUTO_ASSIGNED"
    assert result.assigned_department_id == 1
    assert result.assigned_department_name == "개발1팀"
    assert result.confidence_score == pytest.approx(0.9)
    assert result.score_margin == pytest.approx(0.7)
    assert len(result.candidate_departments) == 2
    assert result.candidate_departments[0].department_id == 1
    assert result.model == "cross-encoder"
    assert result.provider == "qdrant"


def test_recommend_returns_common_queue_when_margin_is_low(service):
    request = TicketRoutingRequest(title="ERP 접근 불가", content="ERP 로그인이 안 됩니다")

    rr_results = [
        _make_rr_candidate(1, "개발1팀", 0.9),
        _make_rr_candidate(2, "개발2팀", 0.7),
    ]
    case_results = [_make_case_candidate(1, "개발1팀", 0.85)]

    with (
        patch("app.domain.ticket_routing.service.settings") as mock_settings,
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        mock_settings.routing_score_threshold = 0.0
        mock_settings.routing_margin_threshold = 0.5
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, case_results]

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert result.assigned_department_id is None
    assert result.assigned_department_name is None
    assert result.confidence_score == pytest.approx(0.9)
    assert result.score_margin == pytest.approx(0.2)


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


def test_recommend_returns_auto_assigned_when_single_candidate_score_passes(service):
    request = TicketRoutingRequest(title="질문", content="내용")

    rr_results = [_make_rr_candidate(1, "개발1팀", 0.9)]

    with (
        patch("app.domain.ticket_routing.service.settings") as mock_settings,
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        mock_settings.routing_single_score_threshold = 0.75
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]

        result = service.recommend(request)

    assert result.decision == "AUTO_ASSIGNED"
    assert result.assigned_department_id == 1
    assert result.assigned_department_name == "개발1팀"
    assert result.confidence_score == pytest.approx(0.9)
    assert result.score_margin is None


def test_recommend_returns_common_queue_when_single_candidate_score_is_low(service):
    request = TicketRoutingRequest(title="질문", content="내용")

    rr_results = [_make_rr_candidate(1, "개발1팀", 0.6)]

    with (
        patch("app.domain.ticket_routing.service.settings") as mock_settings,
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        mock_settings.routing_single_score_threshold = 0.75
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert result.assigned_department_id is None
    assert "단일 후보" in result.reasons[0]


def test_recommend_returns_candidates_sorted_by_embedding_score(service):
    request = TicketRoutingRequest(title="질문", content="내용")

    rr_results = [
        _make_rr_candidate(1, "개발1팀", 0.7),
        _make_rr_candidate(2, "개발2팀", 0.85),
    ]

    with (
        patch("app.domain.ticket_routing.service.settings") as mock_settings,
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
    ):
        # 마진 임계값을 높게 둬 결정은 COMMON_QUEUE로 고정하고, 후보 정렬 순서만 검증한다.
        mock_settings.routing_score_threshold = 0.0
        mock_settings.routing_margin_threshold = 0.5
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]

        result = service.recommend(request)

    assert result.decision == "COMMON_QUEUE"
    assert [c.department_id for c in result.candidate_departments] == [2, 1]


def test_recommend_uses_reranker_to_break_tied_retrieval_scores(service):
    # bi-encoder는 부서를 거의 동점(0.84/0.84)으로 주지만, cross-encoder 재정렬이
    # 인사팀을 확실히 1위로 만들어 자동 배정되게 한다.
    request = TicketRoutingRequest(title="연차신청 문의드립니다", content="연차 신청하고 싶어요")

    rr_results = [
        _make_rr_candidate(2, "인사팀", 0.841),
        _make_rr_candidate(1, "운영관리팀", 0.840),
    ]

    def _discriminate(query, candidates, top_k):
        scores = {2: 0.34, 1: 0.02}  # 재정렬 점수: 인사팀 압도
        return [
            RerankedCandidate(
                candidate_id=c.candidate_id, text=c.text,
                score=scores[c.metadata["department_id"]],
                rank=0, metadata=c.metadata, retrieval_score=c.score,
            )
            for c in candidates
        ]

    with (
        patch("app.domain.ticket_routing.service.settings") as mock_settings,
        patch("app.domain.ticket_routing.service.get_embeddings") as mock_emb,
        patch("app.domain.ticket_routing.service.rag_retriever") as mock_retriever,
        patch("app.domain.ticket_routing.service.get_reranker") as mock_rr,
    ):
        mock_settings.routing_score_threshold = 0.15
        mock_settings.routing_margin_threshold = 0.08
        mock_emb.return_value.embed_query.return_value = [0.1] * 768
        mock_retriever.search_by_embedding.side_effect = [rr_results, []]
        mock_rr.return_value.rerank.side_effect = _discriminate

        result = service.recommend(request)

    assert result.decision == "AUTO_ASSIGNED"
    assert result.assigned_department_id == 2
    assert result.assigned_department_name == "인사팀"
    assert result.confidence_score == pytest.approx(0.34)
    assert result.score_margin == pytest.approx(0.32)


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
