import json
import logging
import re
from urllib.parse import parse_qsl, urlparse, urlunparse

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.exceptions import provider_call
from app.domain.tool_draft.schemas import ToolDraftParameter, ToolDraftRequest, ToolDraftResponse
from app.infra.llm.factory import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 사내 AI Tool 등록 초안을 작성하는 도우미입니다.

관리자가 입력한 HTTP GET API URL을 보고, LLM이 나중에 이 Tool을 잘 선택하고 호출할 수 있도록 Tool 이름, 설명, query parameter 설명을 생성합니다.

규칙:
- name은 snake_case 영어 함수명으로 작성합니다. 동사로 시작하고 40자 이내를 권장합니다.
- description은 한국어 1~2문장으로, 사용자가 어떤 질문을 했을 때 이 Tool을 써야 하는지 명확히 씁니다.
- endpointUrl은 query string과 fragment를 제거한 URL만 반환합니다.
- parameters는 URL query string에 있는 파라미터만 포함합니다.
- parameter description은 LLM이 값을 채울 때 필요한 의미를 한국어로 설명합니다.
- sampleValue가 있으면 그대로 참고해도 됩니다. 사내 통용 식별값은 숨기지 않아도 됩니다.
- 제공되지 않은 API 응답 필드나 권한 정책은 지어내지 않습니다.
- 반드시 아래 JSON 형식으로만 응답합니다. 다른 텍스트·코드펜스 없이.

{
  "name": "lookup_employee",
  "description": "임직원 정보를 이름, 사번, 전화번호 같은 검색어로 조회할 때 사용합니다.",
  "parameters": [
    {"name": "query", "type": "string", "description": "조회할 임직원 이름, 사번, 전화번호 등 검색어입니다.", "required": true}
  ]
}"""


def _strip_query(endpoint_url: str) -> str:
    parsed = urlparse(endpoint_url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _infer_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"true", "false"}:
        return "boolean"
    if re.fullmatch(r"-?\d+", normalized) and not (normalized.startswith("0") and len(normalized) > 1):
        return "integer"
    if re.fullmatch(r"-?\d+\.\d+", normalized):
        return "number"
    return "string"


def _fallback_name(path: str) -> str:
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", path) if p]
    tail = "_".join(p.lower() for p in parts[-3:])
    return f"call_{tail}"[:40] if tail else "call_http_api"


def _fallback_description(endpoint_url: str) -> str:
    host = urlparse(endpoint_url).hostname or "외부 API"
    return f"{host}에서 제공하는 정보를 조회할 때 사용합니다."


class ToolDraftService:
    def draft(self, request: ToolDraftRequest) -> ToolDraftResponse:
        parsed = urlparse(request.endpoint_url)
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        endpoint_url = _strip_query(request.endpoint_url)

        user_message = json.dumps(
            {
                "httpMethod": request.http_method,
                "endpointUrl": request.endpoint_url,
                "path": parsed.path,
                "queryParameters": [
                    {"name": name, "sampleValue": value, "inferredType": _infer_type(value)}
                    for name, value in query_params
                ],
            },
            ensure_ascii=False,
        )
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]

        with provider_call("llm"):
            llm = get_llm(request_timeout=20.0, max_retries=1)
            response = llm.invoke(messages)

        content = response.content if hasattr(response, "content") else str(response)
        return self._parse(content, request.endpoint_url, endpoint_url, query_params)

    def _parse(
        self,
        content: str,
        original_url: str,
        endpoint_url: str,
        query_params: list[tuple[str, str]],
    ) -> ToolDraftResponse:
        text = content.strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                name = self._normalize_name(str(data.get("name", "")))
                description = str(data.get("description", "")).strip()
                parameters = self._parse_parameters(data.get("parameters"), query_params)
                if name and description:
                    return ToolDraftResponse(
                        name=name,
                        description=description,
                        endpoint_url=endpoint_url,
                        parameters=parameters,
                    )
            except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
                pass

        logger.warning("Tool 초안 파싱 실패, URL 기반 fallback을 사용한다.")
        return self._fallback(original_url, endpoint_url, query_params)

    def _parse_parameters(self, raw_parameters: object, query_params: list[tuple[str, str]]) -> list[ToolDraftParameter]:
        by_sample = {name: value for name, value in query_params}
        valid_names = set(by_sample.keys())
        parameters: list[ToolDraftParameter] = []
        if isinstance(raw_parameters, list):
            for item in raw_parameters:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                if name not in valid_names:
                    continue
                param_type = str(item.get("type", _infer_type(by_sample.get(name, "")))).strip()
                if param_type not in {"string", "number", "integer", "boolean"}:
                    param_type = _infer_type(by_sample.get(name, ""))
                description = str(item.get("description", "")).strip() or f"{name} 파라미터입니다."
                parameters.append(ToolDraftParameter(name=name, type=param_type, description=description, required=True))

        used = {p.name for p in parameters}
        for name, value in query_params:
            if name in used:
                continue
            parameters.append(
                ToolDraftParameter(
                    name=name,
                    type=_infer_type(value),
                    description=f"{name} 검색 조건입니다.",
                    required=True,
                )
            )
        return parameters

    def _normalize_name(self, name: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip().lower()).strip("_")
        if not normalized:
            return ""
        if not re.match(r"^[a-z_]", normalized):
            normalized = f"call_{normalized}"
        return normalized[:100]

    def _fallback(
        self,
        original_url: str,
        endpoint_url: str,
        query_params: list[tuple[str, str]],
    ) -> ToolDraftResponse:
        parsed = urlparse(original_url)
        return ToolDraftResponse(
            name=self._normalize_name(_fallback_name(parsed.path)),
            description=_fallback_description(original_url),
            endpoint_url=endpoint_url,
            parameters=[
                ToolDraftParameter(
                    name=name,
                    type=_infer_type(value),
                    description=f"{name} 검색 조건입니다.",
                    required=True,
                )
                for name, value in query_params
            ],
        )


tool_draft_service = ToolDraftService()
