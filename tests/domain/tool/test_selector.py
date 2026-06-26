import json
from unittest.mock import MagicMock, patch

import pytest

from app.common.exceptions import ProviderError
from app.domain.tool.schemas import ToolSelection
from tests.domain.tool.conftest import make_tool


@pytest.fixture
def selector():
    from app.domain.tool.selector import ToolSelector
    return ToolSelector()


def _llm_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.content = json.dumps(payload, ensure_ascii=False)
    return mock


def _tools():
    return [make_tool(tool_id="tool_001")]


def test_returns_none_when_selected_false(selector):
    with patch("app.domain.tool.selector.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response({"selected": False})
        result = selector.select("직원 이름이 뭐야?", _tools())
    assert result is None


def test_returns_selection_when_valid(selector):
    with patch("app.domain.tool.selector.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"selected": True, "tool_id": "tool_001", "inputs": {"employee_id": "E001"}}
        )
        result = selector.select("E001 직원 조회해줘", _tools())
    assert isinstance(result, ToolSelection)
    assert result.tool_id == "tool_001"
    assert result.inputs == {"employee_id": "E001"}


def test_retries_once_on_json_parse_failure(selector):
    bad = MagicMock()
    bad.content = "이건 JSON이 아님"
    good = _llm_response({"selected": True, "tool_id": "tool_001", "inputs": {"employee_id": "E001"}})

    with patch("app.domain.tool.selector.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = [bad, good]
        result = selector.select("조회", _tools())

    assert result is not None
    assert mock_llm.return_value.invoke.call_count == 2


def test_raises_provider_error_after_two_parse_failures(selector):
    bad = MagicMock()
    bad.content = "이건 JSON이 아님"

    with patch("app.domain.tool.selector.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = bad
        with pytest.raises(ProviderError, match="Tool 선택 응답 파싱 실패"):
            selector.select("조회", _tools())

    assert mock_llm.return_value.invoke.call_count == 2


def test_raises_provider_error_on_llm_error(selector):
    with patch("app.domain.tool.selector.get_llm") as mock_llm:
        mock_llm.return_value.invoke.side_effect = ProviderError("llm", "timeout")
        with pytest.raises(ProviderError):
            selector.select("조회", _tools())


def test_raises_provider_error_when_selected_is_string(selector):
    """{"selected": "false"} → Pydantic 타입 검증 실패 → ProviderError."""
    with patch("app.domain.tool.selector.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response({"selected": "false"})
        with pytest.raises(ProviderError, match="Tool 선택 응답 파싱 실패"):
            selector.select("조회", _tools())

    assert mock_llm.return_value.invoke.call_count == 2


def test_raises_provider_error_when_tool_id_is_integer(selector):
    """{"selected": true, "tool_id": 123, "inputs": []} → Pydantic 타입 검증 실패 → ProviderError."""
    with patch("app.domain.tool.selector.get_llm") as mock_llm:
        mock_llm.return_value.invoke.return_value = _llm_response(
            {"selected": True, "tool_id": 123, "inputs": []}
        )
        with pytest.raises(ProviderError, match="Tool 선택 응답 파싱 실패"):
            selector.select("조회", _tools())

    assert mock_llm.return_value.invoke.call_count == 2
