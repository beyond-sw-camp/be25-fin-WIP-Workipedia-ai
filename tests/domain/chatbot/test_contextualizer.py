from unittest.mock import MagicMock, patch
import pytest
from app.domain.chatbot.schemas import SessionMessage
from app.common.exceptions import ProviderError


def _msg(mid: int, role: str, content: str) -> SessionMessage:
    return SessionMessage(message_id=mid, sender_type=role, content=content)


def test_contextualize_empty_history_returns_question():
    from app.domain.chatbot.contextualizer import contextualize
    result = contextualize("며칠 전에?", [])
    assert result == "며칠 전에?"


def test_contextualize_calls_llm_and_returns_text():
    from app.domain.chatbot.contextualizer import contextualize
    mock_response = MagicMock()
    mock_response.content = "연차 신청은 며칠 전에 해야 하나요?"
    with patch("app.domain.chatbot.contextualizer.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        result = contextualize("며칠 전에?", [_msg(1, "USER", "연차 어떻게?"), _msg(2, "ASSISTANT", "HR 포털")])
    assert result == "연차 신청은 며칠 전에 해야 하나요?"


def test_contextualize_empty_llm_response_returns_question():
    from app.domain.chatbot.contextualizer import contextualize
    mock_response = MagicMock()
    mock_response.content = "   "
    with patch("app.domain.chatbot.contextualizer.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        result = contextualize("며칠 전에?", [_msg(1, "USER", "연차 어떻게?")])
    assert result == "며칠 전에?"


def test_contextualize_provider_error_raises():
    from app.domain.chatbot.contextualizer import contextualize
    with patch("app.domain.chatbot.contextualizer.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = ProviderError("llm", "연결 실패")
        with pytest.raises(ProviderError):
            contextualize("며칠 전에?", [_msg(1, "USER", "연차 어떻게?")])


def test_contextualize_too_long_response_returns_question():
    """500자 초과 응답 → 원본 질문 fallback."""
    from app.domain.chatbot.contextualizer import contextualize, _MAX_RETRIEVAL_QUERY_LEN
    mock_response = MagicMock()
    mock_response.content = "A" * (_MAX_RETRIEVAL_QUERY_LEN + 1)
    with patch("app.domain.chatbot.contextualizer.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        result = contextualize("며칠 전에?", [_msg(1, "USER", "연차 어떻게?")])
    assert result == "며칠 전에?"


def test_contextualize_code_fence_response_cleaned():
    """코드 펜스 포함 응답 → 첫 줄 텍스트만 반환."""
    from app.domain.chatbot.contextualizer import contextualize
    mock_response = MagicMock()
    mock_response.content = "```\n연차 신청은 며칠 전에 해야 하나요?\n```"
    with patch("app.domain.chatbot.contextualizer.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = mock_response
        result = contextualize("며칠 전에?", [_msg(1, "USER", "연차 어떻게?")])
    assert result == "연차 신청은 며칠 전에 해야 하나요?"


def test_contextualize_calls_get_llm_with_timeout():
    """`get_llm`이 `request_timeout=settings.contextualize_llm_timeout`으로 호출되는지 확인."""
    from app.domain.chatbot.contextualizer import contextualize
    from app.core.config import settings
    mock_response = MagicMock()
    mock_response.content = "연차 신청 며칠 전에 해야 하나요?"
    with patch("app.domain.chatbot.contextualizer.get_llm") as mock_get_llm:
        mock_get_llm.return_value.invoke.return_value = mock_response
        contextualize("며칠 전에?", [_msg(1, "USER", "연차 어떻게?")])
    mock_get_llm.assert_called_once_with(request_timeout=settings.contextualize_llm_timeout, max_retries=0)
