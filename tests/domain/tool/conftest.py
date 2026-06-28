import pytest

from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult

_UNSET = object()


def make_tool(
    tool_id: str = "tool_001",
    name: str = "직원조회",
    description: str = "직원 정보를 조회한다",
    parameters_schema: dict | None = None,
) -> ToolDefinition:
    if parameters_schema is None:
        parameters_schema = {
            "type": "object",
            "properties": {
                "employee_id": {"type": "string"},
            },
            "required": ["employee_id"],
        }
    return ToolDefinition(
        tool_id=tool_id,
        name=name,
        description=description,
        parameters_schema=parameters_schema,
    )


def make_exec_result(tool_id: str = "tool_001", data=_UNSET) -> ToolExecutionResult:
    """data 미지정 시 기본 데이터 사용. {}, [], None 을 명시적으로 넘길 수 있다."""
    if data is _UNSET:
        data = {"name": "홍길동", "dept": "개발팀"}
    return ToolExecutionResult(tool_id=tool_id, data=data)


class MockToolClient:
    def __init__(
        self,
        tools: list[ToolDefinition] | None = None,
        execute_result: ToolExecutionResult | None = None,
        raise_on_get: Exception | None = None,
        raise_on_execute: Exception | None = None,
    ):
        self._tools = tools or []
        self._execute_result = execute_result
        self._raise_on_get = raise_on_get
        self._raise_on_execute = raise_on_execute

    def get_active_tools(self) -> list[ToolDefinition]:
        if self._raise_on_get:
            raise self._raise_on_get
        return self._tools

    def execute(self, tool_id: str, inputs: dict, caller_employee_id: str | None = None) -> ToolExecutionResult:
        if self._raise_on_execute:
            raise self._raise_on_execute
        return self._execute_result
