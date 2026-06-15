import json
from unittest.mock import MagicMock, patch

import pytest

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.domain.rag.schemas import GeneratedAnswer, RagStatus
from tests.domain.tool.conftest import make_exec_result


@pytest.fixture
def chain():
    from app.domain.tool.chain import ToolResultChain
    return ToolResultChain()


def _llm_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.content = json.dumps(payload, ensure_ascii=False)
    return mock


def test_blocked_when_masking_raises(chain):
    with patch("app.domain.tool.chain.get_llm") as mock_llm, \
         patch("app.domain.tool.chain.masker") as mock_masker:
        mock_llm.return_value.invoke.return_value = _llm_response({"status": "ANSWER", "answer": "답변"})
        mock_masker.mask.side_effect = MaskingBlockedError("차단")
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)
    assert result.status == RagStatus.BLOCKED


def test_no_result_when_insufficient_result(chain):
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response({"status": "INSUFFICIENT_RESULT"})
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_success_with_valid_answer(chain):
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
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

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = [bad, good]
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    assert mock_llm.return_value.invoke.call_count == 2


def test_raises_provider_error_after_two_parse_failures(chain):
    bad = MagicMock()
    bad.content = "이건 JSON이 아님"

    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = bad
        with pytest.raises(ProviderError, match="Tool 결과 응답 파싱 실패"):
            chain.generate("질문", make_exec_result(), custom_prompt=None)

    assert mock_llm.return_value.invoke.call_count == 2


def test_raw_tool_result_passed_to_llm(chain):
    """Tool 결과 원문이 LLM 메시지에 전달되는지 확인."""
    exec_result = make_exec_result()
    with patch("app.domain.tool.chain.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "답변"}
        )
        chain.generate("질문", exec_result, custom_prompt=None)

    messages = mock_llm.return_value.invoke.call_args[0][0]
    import json
    raw_text = json.dumps(exec_result.data, ensure_ascii=False)
    assert raw_text in messages[1].content


def test_answer_is_masked_before_returning(chain):
    """LLM 응답 답변에 마스킹이 적용되는지 확인."""
    with patch("app.domain.tool.chain.get_llm") as mock_llm, \
         patch("app.domain.tool.chain.masker") as mock_masker:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"status": "ANSWER", "answer": "홍길동 010-1234-5678"}
        )
        mock_masker.mask.return_value = "홍길동 [전화번호]"
        result = chain.generate("질문", make_exec_result(), custom_prompt=None)

    assert result.answer.answer == "홍길동 [전화번호]"
