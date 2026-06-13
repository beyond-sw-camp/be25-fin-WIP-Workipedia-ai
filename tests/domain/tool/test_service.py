from unittest.mock import MagicMock

import pytest

from app.common.exceptions import ProviderError, ToolValidationError
from app.domain.rag.schemas import GeneratedAnswer, RagResult, RagStatus
from app.domain.tool.schemas import ToolExecutionResult, ToolSelection
from tests.domain.tool.conftest import MockToolClient, make_exec_result, make_tool


def _make_service(
    tools=None,
    execute_result=None,
    raise_on_get=None,
    raise_on_execute=None,
    selector_result=None,
    selector_raises=None,
    validator_result=None,
    validator_raises=None,
    chain_result=None,
):
    from app.domain.tool.service import ToolService

    client = MockToolClient(
        tools=tools or [],
        execute_result=execute_result,
        raise_on_get=raise_on_get,
        raise_on_execute=raise_on_execute,
    )

    selector = MagicMock()
    if selector_raises:
        selector.select.side_effect = selector_raises
    else:
        selector.select.return_value = selector_result

    validator = MagicMock()
    if validator_raises:
        validator.validate.side_effect = validator_raises
    else:
        validator.validate.return_value = validator_result or {"employee_id": "E001"}

    chain = MagicMock()
    chain.generate.return_value = chain_result or RagResult(
        status=RagStatus.SUCCESS,
        answer=GeneratedAnswer(answer="답변", references=[]),
    )

    return ToolService(client=client, selector=selector, validator=validator, result_chain=chain)


def test_no_result_when_no_active_tools():
    svc = _make_service(tools=[])
    result = svc.run("질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_selector_returns_none():
    svc = _make_service(tools=[make_tool()], selector_result=None)
    result = svc.run("질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_blocked_when_validator_raises():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"x": "y"}),
        validator_raises=ToolValidationError("허용되지 않은 파라미터: ['x']"),
    )
    result = svc.run("질문", custom_prompt=None)
    assert result.status == RagStatus.BLOCKED


def test_no_result_when_execute_returns_empty_dict():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        execute_result=make_exec_result(data={}),
    )
    result = svc.run("질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_execute_returns_empty_list():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        execute_result=make_exec_result(data=[]),
    )
    result = svc.run("질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_execute_returns_none():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        execute_result=make_exec_result(data=None),
    )
    result = svc.run("질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_provider_error_propagates_from_get_active_tools():
    svc = _make_service(raise_on_get=ProviderError("tool", "연결 실패"))
    with pytest.raises(ProviderError, match="연결 실패"):
        svc.run("질문", custom_prompt=None)


def test_provider_error_propagates_from_execute():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        raise_on_execute=ProviderError("tool", "실행 실패"),
    )
    with pytest.raises(ProviderError, match="실행 실패"):
        svc.run("질문", custom_prompt=None)


def test_success_end_to_end():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        execute_result=make_exec_result(data={"name": "홍길동"}),
        chain_result=RagResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(answer="홍길동은 개발팀 소속입니다.", references=[]),
        ),
    )
    result = svc.run("E001이 누구야?", custom_prompt=None)
    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == "홍길동은 개발팀 소속입니다."
    assert result.answer.references == []
