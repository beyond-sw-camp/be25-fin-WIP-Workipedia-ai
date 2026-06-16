from app.common.exceptions import ProviderError, ToolValidationError
from app.domain.tool.schemas import ToolDefinition, ToolSelection


class InputValidator:
    def validate(self, selection: ToolSelection, tool_def_map: dict[str, ToolDefinition]) -> dict:
        if selection.tool_id not in tool_def_map:
            raise ToolValidationError(f"허용되지 않은 tool_id: {selection.tool_id}")

        tool_def = tool_def_map[selection.tool_id]
        schema = tool_def.parameters_schema
        properties = self._properties(schema)
        required_keys = self._required_keys(schema, properties)

        allowed_keys = set(properties.keys())
        extra = set(selection.inputs.keys()) - allowed_keys
        if extra:
            raise ToolValidationError(f"허용되지 않은 파라미터: {sorted(extra)}")

        for key, property_schema in properties.items():
            value = selection.inputs.get(key)
            if value is None:
                if key in required_keys:
                    raise ToolValidationError(f"필수 파라미터가 없습니다: {key}")
                continue

            expected_type = property_schema.get("type")
            if not self._matches_type(value, expected_type):
                raise ToolValidationError(f"파라미터 타입이 올바르지 않습니다: {key}")

        return selection.inputs

    def _properties(self, schema: dict) -> dict[str, dict]:
        raw_properties = schema.get("properties", {})
        if not isinstance(raw_properties, dict):
            raise ProviderError("tool", "Tool 스키마 오류: properties는 object여야 합니다")

        properties: dict[str, dict] = {}
        for key, value in raw_properties.items():
            if not isinstance(value, dict):
                raise ProviderError("tool", f"Tool 스키마 오류: {key} 속성 정의는 object여야 합니다")
            properties[key] = value
        return properties

    def _required_keys(self, schema: dict, properties: dict[str, dict]) -> set[str]:
        required = set()

        # BE 간이 포맷: {"properties": {"field": {"type": "string", "required": true}}}
        for key, property_schema in properties.items():
            if property_schema.get("required") is True:
                required.add(key)

        # 표준 JSON Schema 포맷도 함께 허용: {"required": ["field"]}
        top_level_required = schema.get("required", [])
        if top_level_required is None:
            top_level_required = []
        if not isinstance(top_level_required, list):
            raise ProviderError("tool", "Tool 스키마 오류: required는 array여야 합니다")
        required.update(item for item in top_level_required if isinstance(item, str))
        return required

    def _matches_type(self, value, expected_type: str | None) -> bool:
        if expected_type is None:
            return True
        match expected_type:
            case "string":
                return isinstance(value, str)
            case "integer":
                return isinstance(value, int) and not isinstance(value, bool)
            case "number":
                return isinstance(value, (int, float)) and not isinstance(value, bool)
            case "boolean":
                return isinstance(value, bool)
            case "array":
                return isinstance(value, list)
            case "object":
                return isinstance(value, dict)
            case _:
                # BE ParameterSchemaValidator도 알 수 없는 타입은 통과시킨다.
                return True
