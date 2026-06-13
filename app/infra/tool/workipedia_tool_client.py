import httpx

from app.common.exceptions import ProviderError
from app.core.config import settings
from app.domain.tool.schemas import ToolDefinition, ToolExecutionResult


class WorkipediaToolClient:
    """BE /internal/ai-tools HTTP 클라이언트."""

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._base_url = settings.be_base_url
        self._timeout = settings.tool_http_timeout
        self._transport = transport  # 테스트용 주입 포인트

    def _client(self) -> httpx.Client:
        kwargs: dict = {"base_url": self._base_url, "timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.Client(**kwargs)

    def get_active_tools(self) -> list[ToolDefinition]:
        try:
            with self._client() as client:
                resp = client.get("/internal/ai-tools/active")
                resp.raise_for_status()
                return [
                    ToolDefinition(
                        tool_id=item["toolId"],
                        name=item["name"],
                        description=item["description"],
                        parameters_schema=item["parametersSchema"],
                    )
                    for item in resp.json()
                ]
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError("tool", str(exc)) from exc

    def execute(self, tool_id: str, inputs: dict) -> ToolExecutionResult:
        try:
            with self._client() as client:
                resp = client.post(
                    f"/internal/ai-tools/{tool_id}/execute",
                    json={"inputs": inputs},
                )
                resp.raise_for_status()
                data = resp.json().get("data")
                return ToolExecutionResult(tool_id=tool_id, data=data)
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError, TypeError, AttributeError) as exc:
            raise ProviderError("tool", str(exc)) from exc
