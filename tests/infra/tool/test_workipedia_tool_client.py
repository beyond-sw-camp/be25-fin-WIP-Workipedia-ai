import json

import httpx
import pytest

from app.common.exceptions import ProviderError
from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult


def _make_client(handler):
    """MockTransport로 WorkipediaToolClient를 생성한다."""
    from app.infra.tool.workipedia_tool_client import WorkipediaToolClient
    transport = httpx.MockTransport(handler)
    return WorkipediaToolClient(transport=transport)


# ── get_active_tools ──────────────────────────────────────────────────────────

def test_get_active_tools_returns_tool_list(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "internal_api_key", "test-internal-api-key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/internal/ai-tools/active"
        assert request.headers["X-Internal-Api-Key"] == "test-internal-api-key"
        return httpx.Response(200, json=[
            {
                "aiToolId": 1,
                "name": "직원조회",
                "description": "직원 정보를 조회한다",
                # BE는 parametersSchema를 JSON 컬럼이 아니라 문자열로 직렬화해서 내려준다.
                "parametersSchema": json.dumps({"type": "object", "properties": {"employee_id": {"type": "string"}}}),
            }
        ])

    client = _make_client(handler)
    tools = client.get_active_tools()

    assert len(tools) == 1
    assert isinstance(tools[0], ToolDefinition)
    assert tools[0].tool_id == "1"
    assert tools[0].name == "직원조회"
    assert tools[0].parameters_schema == {"type": "object", "properties": {"employee_id": {"type": "string"}}}


def test_get_active_tools_returns_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    tools = client.get_active_tools()
    assert tools == []


def test_get_active_tools_raises_provider_error_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"})

    client = _make_client(handler)
    with pytest.raises(ProviderError):
        client.get_active_tools()


def test_get_active_tools_raises_provider_error_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "Internal Server Error"})

    client = _make_client(handler)
    with pytest.raises(ProviderError):
        client.get_active_tools()


def test_get_active_tools_raises_provider_error_on_malformed_response():
    """BE가 예상 필드 없는 응답을 반환하면 ProviderError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"unexpected": "field"}])

    client = _make_client(handler)
    with pytest.raises(ProviderError):
        client.get_active_tools()


# ── execute ───────────────────────────────────────────────────────────────────

def test_execute_sends_correct_request_and_returns_result():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/internal/ai-tools/tool_001/execute"
        body = json.loads(request.content)
        assert body == {"parameters": {"employee_id": "E001"}}
        return httpx.Response(200, json={"data": {"name": "홍길동", "dept": "개발팀"}})

    client = _make_client(handler)
    result = client.execute("tool_001", {"employee_id": "E001"})

    assert isinstance(result, ToolExecutionResult)
    assert result.tool_id == "tool_001"
    assert result.data == {"name": "홍길동", "dept": "개발팀"}


def test_execute_raises_provider_error_when_data_key_missing():
    """BE 응답에 'data' 필드 자체가 없으면 ProviderError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    client = _make_client(handler)
    with pytest.raises(ProviderError):
        client.execute("tool_001", {"employee_id": "E001"})


def test_execute_returns_none_when_data_is_null():
    """BE가 {"data": null}을 반환하면 data=None (빈 결과)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": None})

    client = _make_client(handler)
    result = client.execute("tool_001", {"employee_id": "E001"})
    assert result.data is None


def test_execute_raises_provider_error_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "Bad Request"})

    client = _make_client(handler)
    with pytest.raises(ProviderError):
        client.execute("tool_001", {"employee_id": "E001"})


def test_execute_raises_provider_error_on_5xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "Service Unavailable"})

    client = _make_client(handler)
    with pytest.raises(ProviderError):
        client.execute("tool_001", {"employee_id": "E001"})


def test_get_active_tools_raises_provider_error_on_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    client = _make_client(handler)
    with pytest.raises(ProviderError):
        client.get_active_tools()
