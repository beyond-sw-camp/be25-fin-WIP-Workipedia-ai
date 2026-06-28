from unittest.mock import MagicMock, patch

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
    result = svc.run("질문", retrieval_query="질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_selector_returns_none():
    svc = _make_service(tools=[make_tool()], selector_result=None)
    result = svc.run("질문", retrieval_query="질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_validator_raises():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"x": "y"}),
        validator_raises=ToolValidationError("허용되지 않은 파라미터: ['x']"),
    )
    result = svc.run("질문", retrieval_query="질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_execute_returns_empty_dict():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        execute_result=make_exec_result(data={}),
    )
    result = svc.run("질문", retrieval_query="질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_execute_returns_empty_list():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        execute_result=make_exec_result(data=[]),
    )
    result = svc.run("질문", retrieval_query="질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_no_result_when_execute_returns_none():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        execute_result=make_exec_result(data=None),
    )
    result = svc.run("질문", retrieval_query="질문", custom_prompt=None)
    assert result.status == RagStatus.NO_RESULT


def test_provider_error_propagates_from_get_active_tools():
    svc = _make_service(raise_on_get=ProviderError("tool", "연결 실패"))
    with pytest.raises(ProviderError, match="연결 실패"):
        svc.run("질문", retrieval_query="질문", custom_prompt=None)


def test_provider_error_propagates_from_execute():
    svc = _make_service(
        tools=[make_tool()],
        selector_result=ToolSelection(tool_id="tool_001", inputs={"employee_id": "E001"}),
        raise_on_execute=ProviderError("tool", "실행 실패"),
    )
    with pytest.raises(ProviderError, match="실행 실패"):
        svc.run("질문", retrieval_query="질문", custom_prompt=None)


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
    result = svc.run("E001이 누구야?", retrieval_query="E001이 누구야?", custom_prompt=None)
    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == "홍길동은 개발팀 소속입니다."
    assert result.answer.references == []


def test_tool_service_uses_retrieval_query_for_selection():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition, ToolSelection, ToolExecutionResult

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(tool_id="t1", name="잔여연차", description="연차 조회", parameters_schema={})
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = ToolSelection(tool_id="t1", inputs={})
    validator.validate.return_value = {}
    client.execute.return_value = ToolExecutionResult(tool_id="t1", data={"v": 1})
    chain.generate.return_value = RagResult(status=RagStatus.SUCCESS)

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    svc.run(query="잔여 연차 알려줘", retrieval_query="잔여 연차 조회", custom_prompt=None, session_context=[])

    selector.select.assert_called_once_with("잔여 연차 조회", [tool])
    chain.generate.assert_called_once_with(
        "잔여 연차 알려줘",
        client.execute.return_value,
        None,
        session_context=[],
    )


def test_self_only_tool_injects_caller_employee_id_before_validation():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition, ToolSelection, ToolExecutionResult

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(
        tool_id="vacation",
        name="잔여연차",
        description="내 잔여 연차를 조회한다",
        parameters_schema={
            "type": "object",
            "properties": {"employeeId": {"type": "string", "required": True}},
        },
        access_scope="SELF_ONLY",
        self_identity_param="employeeId",
    )
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = ToolSelection(tool_id="vacation", inputs={})
    validator.validate.return_value = {"employeeId": "SA001"}
    client.execute.return_value = ToolExecutionResult(tool_id="vacation", data={"remaining": 7})
    chain.generate.return_value = RagResult(status=RagStatus.SUCCESS)

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    svc.run("내 연차 알려줘", retrieval_query="내 연차 조회", custom_prompt=None, caller_employee_id="SA001")

    injected_selection = validator.validate.call_args.args[0]
    assert injected_selection.inputs == {"employeeId": "SA001"}
    client.execute.assert_called_once_with("vacation", {"employeeId": "SA001"}, caller_employee_id="SA001")


def test_self_only_tool_blocks_other_subject_phone_before_execution():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition, ToolSelection

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(
        tool_id="vacation",
        name="잔여연차",
        description="내 잔여 연차를 조회한다",
        parameters_schema={
            "type": "object",
            "properties": {"employeeId": {"type": "string", "required": True}},
        },
        access_scope="SELF_ONLY",
        self_identity_param="employeeId",
    )
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = ToolSelection(tool_id="vacation", inputs={})

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    result = svc.run(
        "01030923138 이사람 연차 몇개 남았어?",
        retrieval_query="01030923138 이사람 연차 몇개 남았어?",
        custom_prompt=None,
        caller_employee_id="SA001",
    )

    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == "연차 잔여량은 본인 정보만 조회할 수 있습니다. 다른 임직원의 연차 정보는 제공할 수 없습니다."
    validator.validate.assert_not_called()
    client.execute.assert_not_called()
    chain.generate.assert_not_called()


def test_self_only_leave_name_question_falls_back_and_blocks_before_execution():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(
        tool_id="vacation",
        name="잔여연차",
        description="내 잔여 연차를 조회한다",
        parameters_schema={
            "type": "object",
            "properties": {"employeeId": {"type": "string", "required": True}},
        },
        access_scope="SELF_ONLY",
        self_identity_param="employeeId",
    )
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = None

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    result = svc.run(
        "황희수 연차 알려줘",
        retrieval_query="황희수 연차 알려줘",
        custom_prompt=None,
        caller_employee_id="SA001",
    )

    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == "연차 잔여량은 본인 정보만 조회할 수 있습니다. 다른 임직원의 연차 정보는 제공할 수 없습니다."
    validator.validate.assert_not_called()
    client.execute.assert_not_called()
    chain.generate.assert_not_called()


def test_self_only_leave_employee_id_question_blocks_before_employee_lookup_fallback():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    leave_tool = ToolDefinition(
        tool_id="vacation",
        name="잔여연차",
        description="내 잔여 연차를 조회한다",
        parameters_schema={
            "type": "object",
            "properties": {"employeeId": {"type": "string", "required": True}},
        },
        access_scope="SELF_ONLY",
        self_identity_param="employeeId",
    )
    employee_tool = ToolDefinition(
        tool_id="employee",
        name="lookup_employee",
        description="임직원 정보를 이름, 사번, 전화번호 같은 검색어로 조회한다.",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "required": True}},
        },
    )
    client.get_active_tools.return_value = [employee_tool, leave_tool]
    selector.select.return_value = None

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    result = svc.run(
        "sa002 연차 알려줘",
        retrieval_query="sa002 연차 알려줘",
        custom_prompt=None,
        caller_employee_id="SA001",
    )

    assert result.status == RagStatus.SUCCESS
    assert result.answer.answer == "연차 잔여량은 본인 정보만 조회할 수 있습니다. 다른 임직원의 연차 정보는 제공할 수 없습니다."
    validator.validate.assert_not_called()
    client.execute.assert_not_called()
    chain.generate.assert_not_called()


def test_self_only_tool_allows_caller_employee_id_when_explicitly_mentioned():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition, ToolSelection, ToolExecutionResult

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(
        tool_id="vacation",
        name="잔여연차",
        description="내 잔여 연차를 조회한다",
        parameters_schema={
            "type": "object",
            "properties": {"employeeId": {"type": "string", "required": True}},
        },
        access_scope="SELF_ONLY",
        self_identity_param="employeeId",
    )
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = ToolSelection(tool_id="vacation", inputs={})
    validator.validate.return_value = {"employeeId": "SA001"}
    client.execute.return_value = ToolExecutionResult(tool_id="vacation", data={"remaining": 7})
    chain.generate.return_value = RagResult(status=RagStatus.SUCCESS)

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    result = svc.run("SA001 내 연차 알려줘", retrieval_query="SA001 내 연차 알려줘", custom_prompt=None, caller_employee_id="SA001")

    assert result.status == RagStatus.SUCCESS
    client.execute.assert_called_once_with("vacation", {"employeeId": "SA001"}, caller_employee_id="SA001")


def test_weather_question_falls_back_to_seoul_when_selector_returns_none():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(
        tool_id="weather",
        name="get_current_weather",
        description="특정 지역의 현재 날씨를 조회한다. 지역명이 없으면 서울 기준으로 조회한다.",
        parameters_schema={
            "type": "object",
            "properties": {
                "lat": {"type": "number", "required": True},
                "lon": {"type": "number", "required": True},
            },
        },
    )
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = None
    validator.validate.return_value = {"lat": 37.5665, "lon": 126.978}
    client.execute.return_value = ToolExecutionResult(tool_id="weather", data={"temperature": 23.5, "source": "open-meteo"})
    chain.generate.return_value = RagResult(status=RagStatus.SUCCESS)

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    result = svc.run("오늘 날씨 알려줘", retrieval_query="오늘 날씨 알려줘", custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    fallback_selection = validator.validate.call_args.args[0]
    assert fallback_selection.tool_id == "weather"
    assert fallback_selection.inputs == {"lat": 37.5665, "lon": 126.9780}
    client.execute.assert_called_once_with("weather", {"lat": 37.5665, "lon": 126.978}, caller_employee_id=None)


def test_employee_id_question_falls_back_to_employee_lookup_when_selector_returns_none():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(
        tool_id="employee",
        name="lookup_employee",
        description="임직원 정보를 이름, 사번, 전화번호 같은 검색어로 조회한다.",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "required": True}},
        },
    )
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = None
    validator.validate.return_value = {"query": "SA001"}
    client.execute.return_value = ToolExecutionResult(tool_id="employee", data={"matched": True})
    chain.generate.return_value = RagResult(status=RagStatus.SUCCESS)

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    result = svc.run("SA001 이 사람 누구야?", retrieval_query="SA001 이 사람 누구야?", custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    fallback_selection = validator.validate.call_args.args[0]
    assert fallback_selection.tool_id == "employee"
    assert fallback_selection.inputs == {"query": "SA001"}


def test_lowercase_employee_id_question_is_normalized_for_lookup_fallback():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(
        tool_id="employee",
        name="lookup_employee",
        description="임직원 정보를 이름, 사번, 전화번호 같은 검색어로 조회한다.",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "required": True}},
        },
    )
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = None
    validator.validate.return_value = {"query": "SA002"}
    client.execute.return_value = ToolExecutionResult(tool_id="employee", data={"matched": True})
    chain.generate.return_value = RagResult(status=RagStatus.SUCCESS)

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    result = svc.run("sa002는 누구야?", retrieval_query="sa002는 누구야?", custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    fallback_selection = validator.validate.call_args.args[0]
    assert fallback_selection.tool_id == "employee"
    assert fallback_selection.inputs == {"query": "SA002"}


def test_phone_question_falls_back_to_employee_lookup_when_selector_returns_none():
    from app.domain.tool.service import ToolService
    from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult

    client = MagicMock()
    selector = MagicMock()
    validator = MagicMock()
    chain = MagicMock()

    tool = ToolDefinition(
        tool_id="employee",
        name="lookup_employee",
        description="임직원 정보를 이름, 사번, 전화번호 같은 검색어로 조회한다.",
        parameters_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "required": True}},
        },
    )
    client.get_active_tools.return_value = [tool]
    selector.select.return_value = None
    validator.validate.return_value = {"query": "01048998954"}
    client.execute.return_value = ToolExecutionResult(tool_id="employee", data={"matched": True})
    chain.generate.return_value = RagResult(status=RagStatus.SUCCESS)

    svc = ToolService(client=client, selector=selector, validator=validator, result_chain=chain)
    result = svc.run("01048998954가 누구야?", retrieval_query="01048998954가 누구야?", custom_prompt=None)

    assert result.status == RagStatus.SUCCESS
    fallback_selection = validator.validate.call_args.args[0]
    assert fallback_selection.tool_id == "employee"
    assert fallback_selection.inputs == {"query": "01048998954"}
