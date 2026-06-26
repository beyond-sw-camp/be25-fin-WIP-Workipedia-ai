from typing import Protocol

from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult


class ToolClient(Protocol):
    """BE Tool 연동 인터페이스.

    get_active_tools() 실패 시 ProviderError를 발생시킨다 (빈 리스트 반환 금지).
    BE는 active=true AND approvalStatus=APPROVED Tool만 반환한다.
    """

    def get_active_tools(self) -> list[ToolDefinition]: ...

    def execute(self, tool_id: str, inputs: dict) -> ToolExecutionResult: ...
