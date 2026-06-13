from app.common.exceptions import ToolValidationError
from app.domain.rag.schemas import RagResult, RagStatus
from app.domain.tool.client import ToolClient
from app.domain.tool.result_chain import ToolResultChain
from app.domain.tool.selector import ToolSelector
from app.domain.tool.validator import InputValidator


class ToolService:
    def __init__(
        self,
        client: ToolClient,
        selector: ToolSelector,
        validator: InputValidator,
        result_chain: ToolResultChain,
    ) -> None:
        self._client = client
        self._selector = selector
        self._validator = validator
        self._result_chain = result_chain

    def run(self, query: str, custom_prompt: str | None) -> RagResult:
        tools = self._client.get_active_tools()  # ProviderError → 상위 전파
        if not tools:
            return RagResult(status=RagStatus.NO_RESULT)

        selection = self._selector.select(query, tools)  # ProviderError → 상위 전파
        if selection is None:
            return RagResult(status=RagStatus.NO_RESULT)

        tool_def_map = {t.tool_id: t for t in tools}
        try:
            validated_inputs = self._validator.validate(selection, tool_def_map)
        except ToolValidationError:
            return RagResult(status=RagStatus.BLOCKED)

        raw = self._client.execute(selection.tool_id, validated_inputs)  # ProviderError → 상위 전파
        if not raw.data:  # None, {}, []
            return RagResult(status=RagStatus.NO_RESULT)

        return self._result_chain.generate(query, raw, custom_prompt)
