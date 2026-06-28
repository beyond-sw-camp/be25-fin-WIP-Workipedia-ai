import logging
import re
import time

from app.common.exceptions import ToolValidationError
from app.domain.chatbot.schemas import SessionMessage
from app.domain.rag.schemas import GeneratedAnswer, RagResult, RagStatus
from app.domain.tool.client import ToolClient
from app.domain.tool.chain import ToolResultChain
from app.domain.tool.selector import ToolSelector
from app.domain.tool.schemas import ToolDefinition, ToolSelection
from app.domain.tool.validator import InputValidator

logger = logging.getLogger(__name__)

_EMPLOYEE_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,4}\d{2,}(?![A-Za-z0-9])")
_PHONE_LIKE_RE = re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)")
_KOREAN_NAME_LEAVE_RE = re.compile(r"(?<![가-힣])([가-힣]{2,4})(?:님|씨|사원|매니저)?\s*(?:의\s*)?(?:연차|휴가)")
_NON_NAME_LEAVE_PREFIXES = {
    "올해",
    "이번",
    "내년",
    "남은",
    "잔여",
    "전체",
    "현재",
    "오늘",
    "내일",
    "나의",
    "저의",
}


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
        caller_employee_id: str | None = None,
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
            selection = self._fallback_weather_selection(retrieval_query, tools)
        if selection is None:
            selection = self._fallback_self_only_leave_selection(retrieval_query, tools)
        if selection is None:
            selection = self._fallback_employee_lookup_selection(retrieval_query, tools)
        if selection is None:
            logger.warning("[tool_calling] no_tool_selected total_elapsed_ms=%.1f", (time.perf_counter() - started_at) * 1000)
            return RagResult(status=RagStatus.NO_RESULT)

        tool_def_map = {t.tool_id: t for t in tools}
        policy_result = self._block_self_only_other_subject(selection, tool_def_map, retrieval_query, caller_employee_id)
        if policy_result is not None:
            logger.warning("[tool_calling] access_policy=BLOCKED_SELF_ONLY_OTHER_SUBJECT tool_id=%s", selection.tool_id)
            return policy_result

        try:
            validate_started_at = time.perf_counter()
            selection = self._apply_access_scope(selection, tool_def_map, caller_employee_id)
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
        raw = self._client.execute(selection.tool_id, validated_inputs, caller_employee_id=caller_employee_id)  # ProviderError → 상위 전파
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

    def _apply_access_scope(self, selection, tool_def_map: dict[str, object], caller_employee_id: str | None):
        tool = tool_def_map.get(selection.tool_id)
        if tool is None or getattr(tool, "access_scope", "UNRESTRICTED") != "SELF_ONLY":
            return selection
        self_identity_param = getattr(tool, "self_identity_param", None)
        if not self_identity_param or not caller_employee_id:
            return selection
        inputs = dict(selection.inputs)
        inputs[self_identity_param] = caller_employee_id
        return type(selection)(tool_id=selection.tool_id, inputs=inputs)

    def _block_self_only_other_subject(
        self,
        selection: ToolSelection,
        tool_def_map: dict[str, ToolDefinition],
        query: str,
        caller_employee_id: str | None,
    ) -> RagResult | None:
        tool = tool_def_map.get(selection.tool_id)
        if tool is None or tool.access_scope != "SELF_ONLY":
            return None

        self_identity_param = tool.self_identity_param
        selected_identity = str(selection.inputs.get(self_identity_param) or "").strip() if self_identity_param else ""
        if selected_identity and not self._is_same_employee_id(selected_identity, caller_employee_id):
            return self._self_only_other_subject_message()

        if _PHONE_LIKE_RE.search(query):
            return self._self_only_other_subject_message()

        employee_id_match = _EMPLOYEE_ID_RE.search(query)
        if employee_id_match and not self._is_same_employee_id(employee_id_match.group(0), caller_employee_id):
            return self._self_only_other_subject_message()

        if self._has_other_person_name_for_self_only_query(query):
            return self._self_only_other_subject_message()

        return None

    def _is_same_employee_id(self, value: str, caller_employee_id: str | None) -> bool:
        return bool(caller_employee_id) and value.strip().lower() == caller_employee_id.strip().lower()

    def _self_only_other_subject_message(self) -> RagResult:
        return RagResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(
                answer="연차 잔여량은 본인 정보만 조회할 수 있습니다. 다른 임직원의 연차 정보는 제공할 수 없습니다.",
                references=[],
            ),
        )

    def _fallback_weather_selection(self, query: str, tools: list[ToolDefinition]) -> ToolSelection | None:
        normalized_query = query.lower()
        if "날씨" not in normalized_query and "weather" not in normalized_query and "기온" not in normalized_query:
            return None

        for tool in tools:
            label = f"{tool.name} {tool.description}".lower()
            properties = tool.parameters_schema.get("properties", {})
            if not isinstance(properties, dict):
                continue
            has_lat_lon = "lat" in properties and "lon" in properties
            is_weather_tool = "날씨" in label or "weather" in label
            if has_lat_lon and is_weather_tool:
                logger.warning("[tool_calling] fallback_weather_selection tool_id=%s default_location=Seoul", tool.tool_id)
                return ToolSelection(tool_id=tool.tool_id, inputs={"lat": 37.5665, "lon": 126.9780})
        return None

    def _fallback_self_only_leave_selection(self, query: str, tools: list[ToolDefinition]) -> ToolSelection | None:
        normalized_query = query.lower()
        if not any(keyword in normalized_query for keyword in ("연차", "휴가", "잔여일", "잔여량")):
            return None

        for tool in tools:
            label = f"{tool.name} {tool.description}".lower()
            is_self_only_leave_tool = (
                tool.access_scope == "SELF_ONLY"
                and bool(tool.self_identity_param)
                and any(keyword in label for keyword in ("연차", "휴가", "leave", "vacation"))
            )
            if is_self_only_leave_tool:
                logger.warning("[tool_calling] fallback_self_only_leave_selection tool_id=%s", tool.tool_id)
                return ToolSelection(tool_id=tool.tool_id, inputs={})
        return None

    def _fallback_employee_lookup_selection(self, query: str, tools: list[ToolDefinition]) -> ToolSelection | None:
        lookup_value = self._extract_employee_lookup_value(query)
        if lookup_value is None:
            return None

        for tool in tools:
            label = f"{tool.name} {tool.description}".lower()
            properties = tool.parameters_schema.get("properties", {})
            if not isinstance(properties, dict) or "query" not in properties:
                continue
            is_employee_tool = any(keyword in label for keyword in ("임직원", "직원", "employee", "사번", "전화번호"))
            if is_employee_tool:
                logger.warning("[tool_calling] fallback_employee_lookup_selection tool_id=%s query=%s", tool.tool_id, lookup_value)
                return ToolSelection(tool_id=tool.tool_id, inputs={"query": lookup_value})
        return None

    def _extract_employee_lookup_value(self, query: str) -> str | None:
        phone_match = _PHONE_LIKE_RE.search(query)
        if phone_match:
            return phone_match.group(0)

        employee_id_match = _EMPLOYEE_ID_RE.search(query)
        if employee_id_match:
            return employee_id_match.group(0).upper()

        return None

    def _has_other_person_name_for_self_only_query(self, query: str) -> bool:
        match = _KOREAN_NAME_LEAVE_RE.search(query)
        if not match:
            return False
        return match.group(1) not in _NON_NAME_LEAVE_PREFIXES
