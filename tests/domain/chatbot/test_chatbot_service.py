from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.chatbot.schemas import ChatRequest, SessionMessage
from app.domain.chatbot.stream import DoneEvent, TokenEvent
from app.domain.rag.schemas import GeneratedAnswer, OrchestratorResult, RagStatus, StepRecord


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
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)
        mock_policy.decide.return_value.intent = "WORK_SUPPORT"
        result = await service.ask("특수한 질문?!@")
    call_kwargs = mock_orch.run.call_args.kwargs
    assert call_kwargs["query"] == "특수한 질문?!@"
    assert result.action == "CREATE_TICKET"


@pytest.mark.asyncio
async def test_general_question_no_result_returns_chat_without_ticket(service):
    expected = OrchestratorResult(status=RagStatus.NO_RESULT, action="CREATE_TICKET", step_history=[])

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)
        mock_policy.decide.return_value.intent = "GENERAL_CHAT"
        mock_policy.decide.return_value.answer = "사과는 과일이거나 미안함을 전하는 행동입니다."

        result = await service.ask("사과가 뭐야?")

    mock_policy.decide.assert_called_once_with("사과가 뭐야?")
    assert result.status == RagStatus.SUCCESS
    assert result.route == "CHAT"
    assert result.action is None
    assert isinstance(result.answer, GeneratedAnswer)
    assert result.answer.answer == "사과는 과일이거나 미안함을 전하는 행동입니다."
    assert result.answer.references == []


@pytest.mark.asyncio
async def test_general_question_short_circuits_before_rag(service):
    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_policy.decide.return_value.intent = "GENERAL_CHAT"
        mock_policy.decide.return_value.answer = "저는 Workipedia 챗봇입니다."

        result = await service.ask("넌 이름이 뭐야?")

    mock_orch.run.assert_not_called()
    mock_policy.decide.assert_called_once_with("넌 이름이 뭐야?")
    assert result.status == RagStatus.SUCCESS
    assert result.route == "CHAT"
    assert result.answer.answer == "저는 Workipedia 챗봇입니다."


@pytest.mark.asyncio
async def test_work_question_does_not_use_general_short_circuit(service):
    expected = OrchestratorResult(status=RagStatus.SUCCESS, answer=GeneratedAnswer(answer="권한은 관리자에게 요청하세요.", references=[]), route="A")

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)

        result = await service.ask("권한 오류가 뭐야?")

    mock_policy.decide.assert_not_called()
    mock_orch.run.assert_called_once()
    assert result.route == "A"


@pytest.mark.asyncio
async def test_general_question_with_document_candidates_uses_general_fallback(service):
    expected = OrchestratorResult(
        status=RagStatus.NO_RESULT,
        action="CREATE_TICKET",
        step_history=[
            StepRecord(
                step="A",
                status=RagStatus.NO_RESULT,
                retrieval_top_score=0.63,
                retrieval_candidate_count=20,
            )
        ],
    )

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)
        mock_policy.decide.return_value.intent = "GENERAL_CHAT"
        mock_policy.decide.return_value.answer = "한화비전은 방산 회사입니다."

        result = await service.ask("한화비전은 어떤 회사야?")

    assert result.status == RagStatus.SUCCESS
    assert result.route == "CHAT"
    assert result.answer.answer == "한화비전은 방산 회사입니다."
    assert result.answer.references == []


@pytest.mark.asyncio
async def test_work_support_with_document_candidates_returns_insufficient_context_message(service):
    expected = OrchestratorResult(
        status=RagStatus.NO_RESULT,
        action="CREATE_TICKET",
        step_history=[
            StepRecord(
                step="A",
                status=RagStatus.NO_RESULT,
                retrieval_top_score=0.63,
                retrieval_candidate_count=20,
            )
        ],
    )

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)
        mock_policy.decide.return_value.intent = "WORK_SUPPORT"
        mock_policy.decide.return_value.answer = None

        result = await service.ask("한화비전 설치 장애는 어떻게 처리해?")

    assert result.status == RagStatus.SUCCESS
    assert result.route == "CHAT"
    assert "문서에서 관련 후보는 찾았지만" in result.answer.answer
    assert result.answer.references == []


@pytest.mark.asyncio
async def test_work_support_no_result_keeps_create_ticket(service):
    expected = OrchestratorResult(status=RagStatus.NO_RESULT, action="CREATE_TICKET", step_history=[])

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)
        mock_policy.decide.return_value.intent = "WORK_SUPPORT"
        mock_policy.decide.return_value.answer = None

        result = await service.ask("권한 오류가 나요")

    assert result.status == RagStatus.NO_RESULT
    assert result.action == "CREATE_TICKET"


@pytest.mark.asyncio
async def test_successful_work_question_does_not_call_no_result_policy(service):
    answer = GeneratedAnswer(answer="휴가는 HR 포털에서 신청합니다.", references=[])
    expected = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer, route="A", step_history=[])

    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_orch.run = AsyncMock(return_value=expected)

        result = await service.ask("휴가 신청 방법 알려줘")

    mock_policy.decide.assert_not_called()
    assert result.status == RagStatus.SUCCESS
    assert result.route == "A"


@pytest.mark.asyncio
async def test_ticket_confirmation_yes_creates_ticket_without_rag(service):
    context = [
        _msg(1, "USER", "전사 휴일은 언제야?"),
        _msg(2, "ASSISTANT", "관련 문서를 찾지 못했어요. 티켓으로 문의할까요?"),
    ]

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch:
        result = await service.ask("응", session_context=context)

    mock_orch.run.assert_not_called()
    assert result.status == RagStatus.SUCCESS
    assert result.action == "CREATE_TICKET"
    assert result.answer.answer == "좋아요. 티켓을 발행할게요."


@pytest.mark.asyncio
async def test_ticket_confirmation_no_cancels_without_rag(service):
    context = [
        _msg(1, "USER", "전사 휴일은 언제야?"),
        _msg(2, "ASSISTANT", "관련 문서를 찾지 못했어요. 티켓으로 문의할까요?"),
    ]

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch:
        result = await service.ask("아니", session_context=context)

    mock_orch.run.assert_not_called()
    assert result.status == RagStatus.SUCCESS
    assert result.action is None
    assert result.answer.answer == "알겠어요. 티켓은 발행하지 않을게요."


@pytest.mark.asyncio
async def test_ask_stream_applies_no_result_ticket_policy(service):
    expected = OrchestratorResult(status=RagStatus.NO_RESULT, action="CREATE_TICKET", step_history=[])

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_orch.run = AsyncMock(return_value=expected)
        mock_policy.decide.return_value.intent = "WORK_SUPPORT"
        mock_policy.decide.return_value.answer = None

        events = [event async for event in service.ask_stream("전사 휴일은 언제야?")]

    assert isinstance(events[0], TokenEvent)
    assert events[0].content == "관련 문서를 찾지 못했어요. 티켓으로 문의할까요?"
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].action == "CREATE_TICKET"


@pytest.mark.asyncio
async def test_ask_stream_ticket_confirmation_yes_creates_ticket_without_rag(service):
    context = [
        _msg(1, "USER", "전사 휴일은 언제야?"),
        _msg(2, "ASSISTANT", "관련 문서를 찾지 못했어요. 티켓으로 문의할까요?"),
    ]

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch:
        events = [event async for event in service.ask_stream("응", session_context=context)]

    mock_orch.run.assert_not_called()
    assert isinstance(events[0], TokenEvent)
    assert events[0].content == "좋아요. 티켓을 발행할게요."
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].action == "CREATE_TICKET"


@pytest.mark.asyncio
async def test_ask_stream_general_question_short_circuits_before_rag(service):
    with patch("app.domain.chatbot.service.masker") as mock_masker, \
         patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.no_result_policy") as mock_policy:
        mock_masker.mask.side_effect = lambda x: x
        mock_policy.decide.return_value.intent = "GENERAL_CHAT"
        mock_policy.decide.return_value.answer = "안녕하세요. 무엇을 도와드릴까요?"

        events = [event async for event in service.ask_stream("안녕")]

    mock_orch.run.assert_not_called()
    assert isinstance(events[0], TokenEvent)
    assert events[0].content == "안녕하세요. 무엇을 도와드릴까요?"
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].route == "CHAT"


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
    from app.domain.rag.schemas import GeneratedAnswer
    svc = ChatbotService()

    answer_mock = MagicMock(spec=GeneratedAnswer)
    answer_mock.answer = "노출될 수 있는 응답"
    orch_result = OrchestratorResult(status=RagStatus.SUCCESS, answer=answer_mock, step_history=[])

    with patch("app.domain.chatbot.service.rag_orchestrator") as mock_orch, \
         patch("app.domain.chatbot.service.masker") as mock_masker:
        mock_orch.run = AsyncMock(return_value=orch_result)
        mock_masker.mask.side_effect = MaskingBlockedError()
        result = await svc.ask("질문", custom_prompt=None, session_context=[])

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
