import logging
import time

from app.common.exceptions import ToolValidationError
from app.domain.chatbot.schemas import SessionMessage
from app.domain.rag.schemas import RagResult, RagStatus
from app.domain.tool.client import ToolClient
from app.domain.tool.chain import ToolResultChain
from app.domain.tool.selector import ToolSelector
from app.domain.tool.validator import InputValidator

logger = logging.getLogger(__name__)


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

    def run(
        self,
        query: str,
        retrieval_query: str,
        custom_prompt: str | None,
        session_context: list[SessionMessage] | None = None,
    ) -> RagResult:
        started_at = time.perf_counter()

        fetch_started_at = time.perf_counter()
        tools = self._client.get_active_tools()  # ProviderError → 상위 전파
        logger.warning(
            "[tool_calling] active_tools_count=%d elapsed_ms=%.1f",
            len(tools),
            (time.perf_counter() - fetch_started_at) * 1000,
        )
        if not tools:
            logger.warning("[tool_calling] no_active_tools total_elapsed_ms=%.1f", (time.perf_counter() - started_at) * 1000)
            return RagResult(status=RagStatus.NO_RESULT)

        select_started_at = time.perf_counter()
        selection = self._selector.select(retrieval_query, tools)  # ProviderError → 상위 전파
        logger.warning(
            "[tool_calling] selection=%s tool_id=%s input_keys=%s elapsed_ms=%.1f",
            "NONE" if selection is None else "SELECTED",
            None if selection is None else selection.tool_id,
            [] if selection is None else sorted(selection.inputs.keys()),
            (time.perf_counter() - select_started_at) * 1000,
        )
        if selection is None:
            logger.warning("[tool_calling] no_tool_selected total_elapsed_ms=%.1f", (time.perf_counter() - started_at) * 1000)
            return RagResult(status=RagStatus.NO_RESULT)

        tool_def_map = {t.tool_id: t for t in tools}
        try:
            validate_started_at = time.perf_counter()
            validated_inputs = self._validator.validate(selection, tool_def_map)
            logger.warning(
                "[tool_calling] validation=PASS tool_id=%s input_keys=%s elapsed_ms=%.1f",
                selection.tool_id,
                sorted(validated_inputs.keys()),
                (time.perf_counter() - validate_started_at) * 1000,
            )
        except ToolValidationError as exc:
            logger.warning(
                "[tool_calling] validation=NO_RESULT tool_id=%s reason=%s elapsed_ms=%.1f",
                selection.tool_id,
                exc.reason,
                (time.perf_counter() - validate_started_at) * 1000,
            )
            return RagResult(status=RagStatus.NO_RESULT)

        execute_started_at = time.perf_counter()
        raw = self._client.execute(selection.tool_id, validated_inputs)  # ProviderError → 상위 전파
        logger.warning(
            "[tool_calling] execute tool_id=%s data_empty=%s elapsed_ms=%.1f",
            selection.tool_id,
            not bool(raw.data),
            (time.perf_counter() - execute_started_at) * 1000,
        )
        if not raw.data:  # None, {}, []
            logger.warning("[tool_calling] no_result total_elapsed_ms=%.1f", (time.perf_counter() - started_at) * 1000)
            return RagResult(status=RagStatus.NO_RESULT)

        generate_started_at = time.perf_counter()
        result = self._result_chain.generate(query, raw, custom_prompt, session_context=session_context)
        logger.warning(
            "[tool_calling] answer_generation status=%s elapsed_ms=%.1f total_elapsed_ms=%.1f",
            result.status,
            (time.perf_counter() - generate_started_at) * 1000,
            (time.perf_counter() - started_at) * 1000,
        )
        return result
