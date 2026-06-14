from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.domain.rag.schemas import (
    GeneratedAnswer,
    OrchestratorResult,
    RagStatus,
    RerankedCandidate,
)


def _make_ref(cid: str, title: str = "문서", score: float = 1.0) -> RerankedCandidate:
    parts = cid.split(":", 2)
    return RerankedCandidate(
        candidate_id=cid,
        text="내용",
        score=score,
        rank=1,
        metadata={
            "source_type": parts[0] if len(parts) > 1 else "",
            "source_id": parts[1] if len(parts) > 1 else "",
            "title": title,
        },
    )


@pytest.fixture
def client():
    with patch("app.domain.rag.reranker.cross_encoder_reranker.get_reranker"):
        from app.main import app
        return TestClient(app)


# ── SUCCESS ──────────────────────────────────────────────────────────────────

def test_chat_success_response(client):
    answer = GeneratedAnswer(answer="휴가 신청은 HR 포털에서 합니다.", references=[_make_ref("MANUAL:42:0", "휴가 규정")])
    orch_result = OrchestratorResult(
        status=RagStatus.SUCCESS,
        answer=answer,
        route="A",
    )

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "휴가 신청 방법"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "휴가 신청은 HR 포털에서 합니다."
    assert data["route"] == "A"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source_type"] == "MANUAL"
    assert data["sources"][0]["source_id"] == "42"
    assert data["sources"][0]["title"] == "휴가 규정"
    assert data["action"] is None


# ── BLOCKED ──────────────────────────────────────────────────────────────────

def test_chat_blocked_returns_400(client):
    orch_result = OrchestratorResult(status=RagStatus.BLOCKED)

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "민감한 질문"})

    assert response.status_code == 400


# ── CREATE_TICKET ─────────────────────────────────────────────────────────────

def test_chat_create_ticket_action(client):
    orch_result = OrchestratorResult(status=RagStatus.NO_RESULT, action="CREATE_TICKET")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "해결 안 되는 질문"})

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "CREATE_TICKET"
    assert data["answer"] == ""
    assert data["sources"] == []


# ── ERROR ─────────────────────────────────────────────────────────────────────

def test_chat_error_response(client):
    orch_result = OrchestratorResult(status=RagStatus.ERROR)

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    data = response.json()
    assert "다시 시도" in data["answer"]
    assert data["sources"] == []


# ── VALIDATION ────────────────────────────────────────────────────────────────

def test_chat_empty_question_returns_422(client):
    response = client.post("/api/v1/chat", json={"question": ""})
    assert response.status_code == 422


def test_chat_with_session_context(client):
    answer = GeneratedAnswer(answer="3일 전에 해야 합니다.", references=[])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A", step_history=[])

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.asyncio.wait_for", new_callable=AsyncMock) as mock_wait:
        mock_masker.mask.side_effect = lambda x: x
        mock_wait.return_value = "contextualized"
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={
            "question": "며칠 전에?",
            "customPrompt": "친절하게",
            "sessionContext": [
                {"messageId": 1, "senderType": "USER", "content": "연차 어떻게?"},
                {"messageId": 2, "senderType": "ASSISTANT", "content": "HR 포털"},
            ]
        })

    assert response.status_code == 200
    assert response.json()["answer"] == "3일 전에 해야 합니다."


def test_chat_system_sender_type_rejected(client):
    response = client.post("/api/v1/chat", json={
        "question": "질문",
        "sessionContext": [{"messageId": 1, "senderType": "SYSTEM", "content": "시스템"}]
    })
    assert response.status_code == 422


def test_chat_blank_session_content_rejected(client):
    response = client.post("/api/v1/chat", json={
        "question": "질문",
        "sessionContext": [{"messageId": 1, "senderType": "USER", "content": "   "}]
    })
    assert response.status_code == 422
