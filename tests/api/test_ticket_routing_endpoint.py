from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.domain.ticket_routing.schemas import CandidateDepartment, TicketRoutingResponse

client = TestClient(app)


def _auto_assigned_response() -> TicketRoutingResponse:
    return TicketRoutingResponse(
        assigned_department_id=1,
        assigned_department_name="개발1팀",
        confidence_score=5.5,
        score_margin=2.5,
        decision="AUTO_ASSIGNED",
        reasons=["1위 점수 5.5, 점수 차 2.5로 자동 배정 기준 통과"],
        candidate_departments=[
            CandidateDepartment(department_id=1, department_name="개발1팀", confidence_score=5.5),
        ],
        model="bongsoo/kpf-cross-encoder-v1",
        provider="cross-encoder",
    )


def test_routing_returns_200_with_auto_assigned():
    with patch(
        "app.api.v1.endpoints.ticket_routing.ticket_routing_service.recommend",
        return_value=_auto_assigned_response(),
    ):
        response = client.post(
            "/api/v1/tickets/routing",
            json={"title": "ERP 접근 불가", "content": "ERP 로그인이 안 됩니다"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "AUTO_ASSIGNED"
    assert body["assignedDepartmentId"] == 1
    assert body["assignedDepartmentName"] == "개발1팀"
    assert body["confidenceScore"] == pytest.approx(5.5)
    assert body["scoreMargin"] == pytest.approx(2.5)
    assert body["model"] == "bongsoo/kpf-cross-encoder-v1"
    assert body["candidateDepartments"][0]["departmentId"] == 1


def test_routing_returns_422_on_blank_title():
    response = client.post(
        "/api/v1/tickets/routing",
        json={"title": "   ", "content": "내용"},
    )
    assert response.status_code == 422


def test_routing_returns_422_on_missing_content():
    response = client.post(
        "/api/v1/tickets/routing",
        json={"title": "제목"},
    )
    assert response.status_code == 422


def test_routing_accepts_null_source_chatbot_message_id():
    with patch(
        "app.api.v1.endpoints.ticket_routing.ticket_routing_service.recommend",
        return_value=_auto_assigned_response(),
    ):
        response = client.post(
            "/api/v1/tickets/routing",
            json={"title": "제목", "content": "내용", "sourceChatbotMessageId": None},
        )
    assert response.status_code == 200


def test_routing_returns_common_queue_shape():
    common_queue = TicketRoutingResponse(
        assigned_department_id=None,
        assigned_department_name=None,
        confidence_score=None,
        score_margin=None,
        decision="COMMON_QUEUE",
        reasons=["검색 결과 없음"],
        candidate_departments=[],
        model="bongsoo/kpf-cross-encoder-v1",
        provider="cross-encoder",
    )
    with patch(
        "app.api.v1.endpoints.ticket_routing.ticket_routing_service.recommend",
        return_value=common_queue,
    ):
        response = client.post(
            "/api/v1/tickets/routing",
            json={"title": "질문", "content": "내용"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "COMMON_QUEUE"
    assert body["assignedDepartmentId"] is None
    assert body["candidateDepartments"] == []
