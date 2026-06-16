import json

import httpx

from app.common.exceptions import ProviderError
from app.core.config import settings
from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult

_INTERNAL_PREFIX = "/api/v1/internal/ai-tools"


class WorkipediaToolClient:
    """BE /api/v1/internal/ai-tools HTTP 클라이언트."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._base_url = settings.be_base_url
        self._timeout = settings.tool_http_timeout
        self._transport = transport  # 테스트용 주입 포인트

    def _client(self) -> httpx.Client:
        kwargs: dict = {
            "base_url": self._base_url,
            "timeout": self._timeout,
            # BE InternalApiKeyFilter가 /api/v1/internal/** 전체에 요구하는 공유 시크릿.
            "headers": {"X-Internal-Api-Key": settings.internal_api_key},
        }
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def get_active_tools(self) -> list[ToolDefinition]:
        try:
            with self._client() as client:
                resp = client.get(f"{_INTERNAL_PREFIX}/active")
                resp.raise_for_status()
                return [
                    ToolDefinition(
                        tool_id=str(item["aiToolId"]),
                        name=item["name"],
                        description=item["description"],
                        # BE의 parametersSchema는 JSON 컬럼이 아니라 JSON 문자열로 내려온다.
                        parameters_schema=json.loads(item["parametersSchema"]),
                    )
                    for item in resp.json()
                ]
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError("tool", str(exc)) from exc

    def execute(self, tool_id: str, inputs: dict) -> ToolExecutionResult:
        try:
            with self._client() as client:
                resp = client.post(
                    f"{_INTERNAL_PREFIX}/{tool_id}/execute",
                    json={"parameters": inputs},
                )
                resp.raise_for_status()
                body = resp.json()
                if "data" not in body:
                    raise KeyError(f"BE 응답에 'data' 필드 누락: {body}")
                data = body["data"]
                if data is not None and not isinstance(data, (dict, list)):
                    raise TypeError(f"BE 응답 'data' 타입 오류: {type(data).__name__}")
                return ToolExecutionResult(tool_id=tool_id, data=data)
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError("tool", str(exc)) from exc
