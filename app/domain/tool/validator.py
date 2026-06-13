import jsonschema

from app.common.exceptions import ProviderError, ToolValidationError
from app.domain.tool.schemas import ToolDefinition, ToolSelection


class InputValidator:
    def validate(self, selection: ToolSelection, tool_def_map: dict[str, ToolDefinition]) -> dict:
        if selection.tool_id not in tool_def_map:
            raise ToolValidationError(f"허용되지 않은 tool_id: {selection.tool_id}")

        tool_def = tool_def_map[selection.tool_id]
        schema = tool_def.parameters_schema
        allowed_keys = set(schema.get("properties", {}).keys())
        extra = set(selection.inputs.keys()) - allowed_keys
        if extra:
            raise ToolValidationError(f"허용되지 않은 파라미터: {sorted(extra)}")

        try:
            jsonschema.validate(instance=selection.inputs, schema=schema)
        except jsonschema.ValidationError as exc:
            raise ToolValidationError(f"스키마 검증 실패: {exc.message}") from exc
        except jsonschema.SchemaError as exc:
            raise ProviderError("tool", f"Tool 스키마 오류: {exc.message}") from exc

        return selection.inputs
