from app.core.config import settings
from app.domain.tool.client import ToolClient
from app.infra.tool.stub_tool_client import StubToolClient
from app.infra.tool.workipedia_tool_client import WorkipediaToolClient


def get_tool_client() -> ToolClient:
    """TOOL_CLIENT 환경변수로 클라이언트를 선택한다. 허용값: 'stub', 'workipedia'."""
    if settings.tool_client == "workipedia":
        return WorkipediaToolClient()
    if settings.tool_client == "stub":
        return StubToolClient()
    raise ValueError(
        f"알 수 없는 TOOL_CLIENT 값: '{settings.tool_client}'. 허용값: 'stub', 'workipedia'"
    )
