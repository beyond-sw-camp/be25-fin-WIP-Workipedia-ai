from dataclasses import dataclass
from typing import Any


@dataclass
class ToolDefinition:
    tool_id: str
    name: str
    description: str
    parameters_schema: dict[str, Any]  # JSON Schema (BE에서 받은 그대로)


@dataclass
class ToolSelection:
    tool_id: str
    inputs: dict[str, Any]  # LLM이 선택한 인자


@dataclass
class ToolExecutionResult:
    tool_id: str
    data: dict[str, Any] | list[Any] | None  # None / {} / [] 은 빈 결과
