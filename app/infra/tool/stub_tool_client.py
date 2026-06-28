from app.common.exceptions import ProviderError
from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult


class StubToolClient:
    """BE 연동 전 기본 클라이언트. 빈 목록을 반환해 NO_RESULT로 흐른다."""

    def get_active_tools(self) -> list[ToolDefinition]:
        return []

    def execute(self, tool_id: str, inputs: dict, caller_employee_id: str | None = None) -> ToolExecutionResult:
        raise ProviderError("tool", "stub client — BE not connected")
