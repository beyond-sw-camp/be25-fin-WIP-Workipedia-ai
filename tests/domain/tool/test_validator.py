import pytest

import jsonschema

from app.common.exceptions import ProviderError, ToolValidationError
from app.domain.tool.schemas import ToolSelection
from tests.domain.tool.conftest import make_tool


@pytest.fixture
def validator():
    from app.domain.tool.validator import InputValidator
    return InputValidator()


_UNSET = object()


def _make_sel(tool_id: str = "tool_001", inputs=_UNSET) -> ToolSelection:
    if inputs is _UNSET:
        inputs = {"employee_id": "E001"}
    return ToolSelection(tool_id=tool_id, inputs=inputs)


def _def_map(tool_id: str = "tool_001"):
    return {tool_id: make_tool(tool_id=tool_id)}


def test_blocked_when_tool_id_unknown(validator):
    sel = _make_sel(tool_id="unknown_tool")
    with pytest.raises(ToolValidationError, match="허용되지 않은 tool_id"):
        validator.validate(sel, _def_map())


def test_blocked_when_extra_param_included(validator):
    sel = _make_sel(inputs={"employee_id": "E001", "secret": "hack"})
    with pytest.raises(ToolValidationError, match="허용되지 않은 파라미터"):
        validator.validate(sel, _def_map())


def test_blocked_when_required_param_missing(validator):
    sel = _make_sel(inputs={})
    with pytest.raises(ToolValidationError, match="스키마 검증 실패"):
        validator.validate(sel, _def_map())


def test_blocked_when_param_wrong_type(validator):
    sel = _make_sel(inputs={"employee_id": 12345})
    with pytest.raises(ToolValidationError, match="스키마 검증 실패"):
        validator.validate(sel, _def_map())


def test_returns_inputs_when_valid(validator):
    sel = _make_sel(inputs={"employee_id": "E001"})
    result = validator.validate(sel, _def_map())
    assert result == {"employee_id": "E001"}


def test_provider_error_when_schema_is_invalid(validator):
    """BE가 잘못된 JSON Schema를 반환한 경우 → ProviderError (BLOCKED 아님)."""
    broken_schema_tool = make_tool(
        parameters_schema={"type": "INVALID_TYPE", "properties": {"x": {"type": "string"}}}
    )
    sel = _make_sel(inputs={"x": "value"})
    with pytest.raises(ProviderError, match="Tool 스키마 오류"):
        validator.validate(sel, {"tool_001": broken_schema_tool})
