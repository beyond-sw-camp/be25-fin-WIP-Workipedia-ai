from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.chatbot.schemas import ChatRequest, SessionMessage
from app.domain.rag.schemas import OrchestratorResult, RagStatus


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


def _msg(mid, role, content):
    return SessionMessage(message_id=mid, sender_type=role, content=content)


# ── 기존 테스트 (새 파이프라인에 맞게 업데이트) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_delegates_to_orchestrator(service):
    expected = OrchestratorResult(status=RagStatus.SUCCESS, step_history=[])
    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)
        result = await service.ask("질문")
    mock_orch.run.assert_called_once()
    assert result is expected


@pytest.mark.asyncio
async def test_ask_passes_question_unchanged(service):
    expected = OrchestratorResult(status=RagStatus.NO_RESULT, action="CREATE_TICKET", step_history=[])
    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)
        result = await service.ask("특수한 질문?!@")
    call_kwargs = mock_orch.run.call_args.kwargs
    assert call_kwargs["query"] == "특수한 질문?!@"
    assert result.action == "CREATE_TICKET"


# ── 새 파이프라인 테스트 ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ask_masks_and_contextualizes():
    from app.domain.chatbot.service import ChatbotService
    svc = ChatbotService()
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=MagicMock(references=[]), step_history=[])

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.asyncio") as mock_asyncio, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch:

        mock_masker.mask.side_effect = lambda x: x
        mock_asyncio.wait_for = AsyncMock(return_value="contextualized")
        mock_asyncio.to_thread = MagicMock(return_value="thread_coro")
        mock_asyncio.TimeoutError = TimeoutError
        mock_orch.run = AsyncMock(return_value=orch_result)

        context = [_msg(1, "USER", "연차 어떻게?")]
        await svc.ask("며칠 전에?", custom_prompt=None, session_context=context)

        mock_orch.run.assert_called_once()
        call_kwargs = mock_orch.run.call_args.kwargs
        assert call_kwargs["query"] == "며칠 전에?"
        assert call_kwargs["retrieval_query"] == "contextualized"


@pytest.mark.asyncio
async def test_ask_masking_blocked_returns_blocked():
    from app.domain.chatbot.service import ChatbotService
    from app.common.exceptions import MaskingBlockedError
    svc = ChatbotService()

    with patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_masker.mask.side_effect = MaskingBlockedError()
        result = await svc.ask("주민번호 노출 질문", custom_prompt=None, session_context=[])

    assert result.status == RagStatus.BLOCKED


@pytest.mark.asyncio
async def test_ask_contextualize_provider_error_fallback_and_logs():
    from app.domain.chatbot.service import ChatbotService
    from app.common.exceptions import ProviderError
    svc = ChatbotService()
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=MagicMock(references=[]), step_history=[])

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.asyncio.wait_for", new_callable=AsyncMock) as mock_wait:

        mock_masker.mask.side_effect = lambda x: x
        mock_wait.side_effect = ProviderError("llm", "연결 실패")
        mock_orch.run = AsyncMock(return_value=orch_result)

        result = await svc.ask("며칠 전에?", custom_prompt=None, session_context=[_msg(1, "USER", "연차 어떻게?")])

    assert result.step_history[0].step == "CONTEXT"
    assert result.step_history[0].status == RagStatus.ERROR
    call_kwargs = mock_orch.run.call_args.kwargs
    assert call_kwargs["retrieval_query"] == "며칠 전에?"


@pytest.mark.asyncio
async def test_ask_trims_to_max_context_messages():
    from app.domain.chatbot.service import ChatbotService
    from app.core.config import settings
    svc = ChatbotService()
    orch_result = OrchestratorResult(status=RagStatus.NO_RESULT, step_history=[])

    context = [_msg(i, "USER" if i % 2 else "ASSISTANT", f"msg{i}") for i in range(1, 6)]

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.asyncio.wait_for", new_callable=AsyncMock) as mock_wait, \
         patch.object(settings, "max_context_messages", 2):

        mock_masker.mask.side_effect = lambda x: x
        mock_wait.return_value = "q"
        mock_orch.run = AsyncMock(return_value=orch_result)

        await svc.ask("질문", custom_prompt=None, session_context=context)

    call_kwargs = mock_orch.run.call_args.kwargs
    passed_context = call_kwargs["session_context"]
    assert len(passed_context) == 2
    assert passed_context[0].message_id == 4
    assert passed_context[1].message_id == 5


@pytest.mark.asyncio
async def test_ask_max_context_zero_disables_history():
    from app.domain.chatbot.service import ChatbotService
    from app.core.config import settings
    svc = ChatbotService()
    orch_result = OrchestratorResult(status=RagStatus.NO_RESULT, step_history=[])

    context = [_msg(1, "USER", "이전 대화")]

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch.object(settings, "max_context_messages", 0):

        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=orch_result)

        await svc.ask("질문", custom_prompt=None, session_context=context)

    call_kwargs = mock_orch.run.call_args.kwargs
    assert call_kwargs["session_context"] == []
    assert call_kwargs["retrieval_query"] == "질문"
