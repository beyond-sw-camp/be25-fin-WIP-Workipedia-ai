from unittest.mock import AsyncMock, patch

import pytest

from app.domain.rag.schemas import OrchestratorResult, RagStatus
from app.domain.chatbot.schemas import ChatRequest, SessionMessage


def test_session_message_valid():
    msg = SessionMessage(messageId=1, senderType="USER", content="안녕")
    assert msg.message_id == 1
    assert msg.sender_type == "USER"

def test_session_message_rejects_system():
    with pytest.raises(Exception):
        SessionMessage(messageId=1, senderType="SYSTEM", content="x")

def test_session_message_blank_content_rejected():
    with pytest.raises(Exception):
        SessionMessage(messageId=1, senderType="USER", content="   ")

def test_chat_request_default_context():
    req = ChatRequest(question="질문")
    assert req.session_context == []
    assert req.custom_prompt is None

def test_chat_request_with_context():
    req = ChatRequest(
        question="며칠 전에?",
        customPrompt="친절하게",
        sessionContext=[{"messageId": 1, "senderType": "USER", "content": "연차 어떻게?"},
                       {"messageId": 2, "senderType": "ASSISTANT", "content": "HR 포털"}]
    )
    assert len(req.session_context) == 2
    assert req.custom_prompt == "친절하게"


@pytest.fixture
def service():
    from app.domain.chatbot.service import ChatbotService
    return ChatbotService()


@pytest.mark.asyncio
async def test_ask_delegates_to_orchestrator(service):
    expected = OrchestratorResult(status=RagStatus.SUCCESS)
    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch:
        mock_orch.run = AsyncMock(return_value=expected)
        result = await service.ask("질문")
    mock_orch.run.assert_called_once_with("질문")
    assert result is expected


@pytest.mark.asyncio
async def test_ask_passes_question_unchanged(service):
    expected = OrchestratorResult(status=RagStatus.NO_RESULT, action="CREATE_TICKET")
    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch:
        mock_orch.run = AsyncMock(return_value=expected)
        result = await service.ask("특수한 질문?!@")
    mock_orch.run.assert_called_once_with("특수한 질문?!@")
    assert result.action == "CREATE_TICKET"
