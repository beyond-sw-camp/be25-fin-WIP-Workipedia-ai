import json
from unittest.mock import MagicMock, patch

import pytest

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.domain.rag.schemas import GeneratedAnswer, RagStatus
from tests.domain.tool.conftest import make_exec_result


@pytest.fixture
def chain():
    from app.domain.tool.result_chain import ToolResultChain
    return ToolResultChain()


def _llm_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.content = json.dumps(payload, ensure_ascii=False)
    return mock


def test_blocked_when_masking_raises(chain):
    with patch("app.domain.tool.result_chain.masker") as mock_masker:
        mock_masker.mask.side_effect = MaskingBlockedError("차단")
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)
    assert result.status == RagStatus.BLOCKED


def test_no_result_when_insufficient_result(chain):
    with patch("app.domain.tool.result_chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response({"status": "INSUFFICIENT_RESULT"})
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_success_with_valid_answer(chain):
    with patch("app.domain.tool.result_chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "홍길동은 개발팀 소속입니다."}
        )
        result = chain.generate("E001이 누구야?", make_exec_result(), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert isinstance(result.answer, GeneratedAnswer)
    assert result.answer.answer == "홍길동은 개발팀 소속입니다."
    assert result.answer.references == []


def test_retries_once_on_parse_failure(chain):
    bad = MagicMock()
    bad.content = "이건 JSON이 아님"
    good = _llm_response({"status": "ANSWER", "answer": "답변"})

    with patch("app.domain.tool.result_chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = [bad, good]
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert mock_llm.return_value.invoke.call_count == 2


def test_raises_provider_error_after_two_parse_failures(chain):
    bad = MagicMock()
    bad.content = "이건 JSON이 아님"

    with patch("app.domain.tool.result_chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = bad
        with pytest.raises(ProviderError, match="Tool 결과 응답 파싱 실패"):
            chain.generate("질문", make_exec_result(), custom_prompt=None)

    assert mock_llm.return_value.invoke.call_count == 2


def test_masked_result_passed_to_llm(chain):
    """마스킹된 텍스트가 LLM 메시지에 포함되는지 확인."""
    with patch("app.domain.tool.result_chain.masker") as mock_masker, \
         patch("app.domain.tool.result_chain.get_llm") as mock_llm:
        mock_masker.mask.return_value = "[마스킹됨]"
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "답변"}
        )
        chain.generate("질문", make_exec_result(), custom_prompt=None)

    messages = mock_llm.return_value.invoke.call_args[0][0]
    assert "[마스킹됨]" in messages[1].content


def test_numeric_pii_is_masked_via_serialized_string(chain):
    """숫자형 개인정보(카드번호)가 직렬화 후 2차 마스킹에서 처리되는지 확인."""
    from app.domain.tool.result_chain import _mask_tool_result
    result = _mask_tool_result({"cardNumber": 1234567890123456, "name": "홍길동"})
    assert "1234567890123456" not in result
    assert "[카드번호]" in result
