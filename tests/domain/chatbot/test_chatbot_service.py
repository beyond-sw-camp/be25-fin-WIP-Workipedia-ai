from unittest.mock import AsyncMock, patch

import pytest

from app.domain.rag.schemas import OrchestratorResult, RagStatus


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
