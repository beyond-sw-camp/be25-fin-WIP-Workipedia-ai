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
    meta = {
        "source_type": parts[0] if len(parts) > 1 else "",
        "source_id": parts[1] if len(parts) > 1 else "",
        "title": title,
    }
    if len(parts) == 3:
        try:
            meta["chunk_index"] = int(parts[2])
        except (ValueError, TypeError):
            pass
    return RerankedCandidate(
        candidate_id=cid,
        text="내용",
        score=score,
        rank=1,
        metadata=meta,
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
    assert data["sources"][0]["chunk_index"] == 0
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
         patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        mock_policy.decide.return_value.intent = "WORK_SUPPORT"
        mock_policy.decide.return_value.answer = None
        response = client.post("/api/v1/chat", json={"question": "해결 안 되는 질문"})

    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "CREATE_TICKET"
    assert data["answer"] == "관련 문서를 찾지 못했어요. 티켓으로 문의할까요?"
    assert data["sources"] == []


def test_chat_ticket_confirmation_keeps_create_ticket_action(client):
    response = client.post("/api/v1/chat", json={
        "question": "응",
        "sessionContext": [
            {"messageId": 1, "senderType": "USER", "content": "전사 휴일은 언제야?"},
            {"messageId": 2, "senderType": "ASSISTANT", "content": "관련 문서를 찾지 못했어요. 티켓으로 문의할까요?"},
        ],
    })

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "좋아요. 티켓을 발행할게요."
    assert data["action"] == "CREATE_TICKET"
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


def test_chat_source_chunk_index_metadata_takes_priority(client):
    """metadata chunk_index가 candidate_id 파싱값보다 우선한다."""
    ref = RerankedCandidate(
        candidate_id="MANUAL:42:9",   # candidate_id에서 파싱하면 9
        text="내용",
        score=1.0,
        rank=1,
        metadata={
            "source_type": "MANUAL",
            "source_id": "42",
            "chunk_index": 0,          # metadata 값은 0
            "title": "휴가 규정",
        },
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    assert response.json()["sources"][0]["chunk_index"] == 0  # metadata 값 우선


def test_chat_source_includes_page_range_metadata(client):
    ref = RerankedCandidate(
        candidate_id="MANUAL:42:9",
        text="내용",
        score=1.0,
        rank=1,
        metadata={
            "source_type": "MANUAL",
            "source_id": "42",
            "chunk_index": 9,
            "page_start": 20,
            "page_end": 21,
            "title": "LoRA.pdf",
        },
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert source["page_start"] == 20
    assert source["page_end"] == 21


def test_chat_source_includes_file_name(client):
    ref = RerankedCandidate(
        candidate_id="MANUAL:42:0",
        text="내용",
        score=1.0,
        rank=1,
        metadata={
            "source_type": "MANUAL",
            "source_id": "42",
            "chunk_index": 0,
            "file_name": "file2.pdf",
            "page_start": 1,
            "page_end": 2,
            "title": "소개서",
        },
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert source["file_name"] == "file2.pdf"
    assert source["page_start"] == 1
    assert source["page_end"] == 2


def test_chat_source_chunk_index_from_candidate_id_fallback(client):
    """metadata에 chunk_index가 없으면 candidate_id 파싱으로 fallback한다."""
    ref = RerankedCandidate(
        candidate_id="MANUAL:7:3",
        text="내용",
        score=1.0,
        rank=1,
        metadata={"source_type": "MANUAL", "source_id": "7", "title": "매뉴얼"},
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    assert response.json()["sources"][0]["chunk_index"] == 3


def test_chat_source_chunk_index_invalid_metadata_falls_back_to_candidate_id(client):
    """metadata chunk_index가 변환 불가이면 candidate_id 파싱으로 fallback한다."""
    ref = RerankedCandidate(
        candidate_id="MANUAL:7:5",
        text="내용",
        score=1.0,
        rank=1,
        metadata={"source_type": "MANUAL", "source_id": "7", "chunk_index": "invalid", "title": "매뉴얼"},
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    assert response.json()["sources"][0]["chunk_index"] == 5


def test_chat_source_chunk_index_none_when_not_parseable(client):
    """chunk_index가 metadata와 candidate_id 모두에 없으면 null을 반환한다."""
    ref = RerankedCandidate(
        candidate_id="MANUAL:5",
        text="내용",
        score=1.0,
        rank=1,
        metadata={"source_type": "MANUAL", "source_id": "5", "title": "제목"},
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    assert response.json()["sources"][0]["chunk_index"] is None


def test_chat_source_candidate_id_fallback_used_when_metadata_missing(client):
    """metadata에 source_type/source_id가 없으면 candidate_id 파싱 fallback으로 정상 반환한다."""
    ref = RerankedCandidate(
        candidate_id="MANUAL:42:0",  # 파싱 가능
        text="내용",
        score=1.0,
        rank=1,
        metadata={},  # metadata 비어 있음
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    data = response.json()
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source_type"] == "MANUAL"
    assert data["sources"][0]["source_id"] == "42"


def test_chat_source_skipped_when_both_metadata_and_candidate_id_unparseable(client):
    """metadata도 비어 있고 candidate_id도 파싱 불가능하면 해당 source는 제외되고 500은 발생하지 않는다."""
    bad_ref = RerankedCandidate(
        candidate_id="opaque-id",  # : 구분자 없음
        text="내용",
        score=1.0,
        rank=1,
        metadata={},  # metadata도 비어 있음
    )
    good_ref = RerankedCandidate(
        candidate_id="MANUAL:42:0",
        text="정상 내용",
        score=0.9,
        rank=2,
        metadata={"source_type": "MANUAL", "source_id": "42", "chunk_index": 0, "title": "휴가 규정"},
    )
    answer = GeneratedAnswer(answer="답변", references=[bad_ref, good_ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    data = response.json()
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source_type"] == "MANUAL"


@pytest.mark.parametrize("source_type,source_id", [
    ("MANUAL", "10"),
    ("WORKI", "20"),
    ("KNOWLEDGE_DATA", "30"),
    ("MANUAL_KNOWLEDGE", "40"),
])
def test_chat_all_source_types_returned(client, source_type, source_id):
    """4가지 source_type 모두 sources에 포함된다."""
    ref = RerankedCandidate(
        candidate_id=f"{source_type}:{source_id}:0",
        text="내용",
        score=1.0,
        rank=1,
        metadata={
            "source_type": source_type,
            "source_id": source_id,
            "chunk_index": 0,
            "title": f"{source_type} 문서",
        },
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert source["source_type"] == source_type
    assert source["source_id"] == source_id
    assert source["chunk_index"] == 0
    assert source["title"] == f"{source_type} 문서"


def test_chat_source_id_int_in_metadata_converted_to_str(client):
    """metadata의 source_id가 int로 저장되어도 str로 변환된다."""
    ref = RerankedCandidate(
        candidate_id="MANUAL:99:0",
        text="내용",
        score=1.0,
        rank=1,
        metadata={
            "source_type": "MANUAL",
            "source_id": 99,  # int
            "chunk_index": 0,
            "title": "테스트 문서",
        },
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    assert response.json()["sources"][0]["source_id"] == "99"


def test_chat_source_fields_from_metadata_only(client):
    """candidate_id 파싱 없이 metadata만으로 모든 출처 필드가 채워진다."""
    ref = RerankedCandidate(
        candidate_id="opaque-id",  # 파싱 불가능한 ID, metadata로만 동작
        text="내용",
        score=0.95,
        rank=1,
        metadata={
            "source_type": "WORKI",
            "source_id": "77",
            "chunk_index": 3,
            "title": "워키 게시글",
        },
    )
    answer = GeneratedAnswer(answer="답변", references=[ref])
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="B")

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)
        response = client.post("/api/v1/chat", json={"question": "질문"})

    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert source["source_type"] == "WORKI"
    assert source["source_id"] == "77"
    assert source["chunk_index"] == 3
    assert source["title"] == "워키 게시글"
    assert source["page_start"] is None
    assert source["page_end"] is None
