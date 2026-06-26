import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.common.exceptions import ProviderError, provider_call
from app.common.masking import masker
from app.domain.department.schemas import (
    DepartmentRoutingResult,
    DepartmentTarget,
    RoutingPromptRequest,
    RoutingPromptResponse,
)
from app.infra.llm.factory import get_llm

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """당신은 부서 역할 설명(routing prompt)을 관리하는 AI입니다.

관리자가 자연어로 변경 지시를 내리면, 변경이 필요한 부서의 최종 역할 설명을 생성해야 합니다.

규칙:
- 변경이 필요한 부서만 결과에 포함합니다. 변경이 없는 부서는 포함하지 않습니다.
- 대상 부서의 현재 역할이 있으면 절대 삭제하지 말고, 현재 역할에 변경 지시의 역할을 추가·병합한 "최종 완성 문장"을 반환합니다. 명시적으로 "삭제", "제거", "교체", "대체"하라는 지시가 있을 때만 기존 역할을 줄이거나 바꿉니다.
- 현재 역할과 추가 역할을 자연스러운 한 문장으로 병합합니다. 같은 내용을 반복하거나 문장을 단순히 이어 붙이지 않습니다.
- 부서명은 포함하지 말고 역할만 짧고 명확하게 작성합니다. (예: "검색과 RAG를 담당한다.")
- 민감정보(주민번호, 카드번호, 전화번호, 이메일 등)를 응답에 포함하지 않습니다.
- 반드시 아래 JSON 형식으로만 응답합니다. 다른 텍스트는 포함하지 않습니다.

응답 형식:
{"results": [{"departmentId": <int>, "routingPrompt": "<string>"}]}"""


def _build_user_message(instruction: str, targets: list[DepartmentTarget]) -> str:
    dept_list = "\n".join(
        f"- departmentId: {t.department_id}, 부서명: {t.department_name}, 현재 역할: {t.current_prompt}"
        for t in targets
    )
    return f"변경 지시: {instruction}\n\n대상 부서:\n{dept_list}"


def _parse_llm_response(content: str, targets: list[DepartmentTarget]) -> list[DepartmentRoutingResult]:
    valid_ids = {t.department_id for t in targets}
    try:
        data = json.loads(content.strip())
        raw_results = data.get("results", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise ProviderError("llm", f"LLM 응답을 JSON으로 파싱할 수 없습니다: {exc}") from exc

    if not isinstance(raw_results, list):
        raise ProviderError("llm", f"LLM 응답의 results가 리스트가 아닙니다: {type(raw_results).__name__}")

    results = []
    for item in raw_results:
        dept_id = item.get("departmentId")
        prompt = item.get("routingPrompt", "")
        if dept_id not in valid_ids:
            logger.warning("LLM이 요청에 없는 departmentId %s를 반환했습니다. 무시합니다.", dept_id)
            continue
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderError("llm", f"departmentId {dept_id}의 routingPrompt가 비어있거나 올바르지 않습니다.")
        # 현재 역할과의 병합은 LLM이 시스템 프롬프트 지시에 따라 직접 수행한다.
        # 코드에서 다시 이어 붙이면 LLM이 이미 병합한 문장과 중복되므로 그대로 사용한다.
        masked_prompt = masker.mask(prompt.strip())
        results.append(DepartmentRoutingResult(department_id=dept_id, routing_prompt=masked_prompt))
    return results


class DepartmentRoutingPromptService:
    def generate(self, request: RoutingPromptRequest) -> RoutingPromptResponse:
        user_message = _build_user_message(request.instruction, request.targets)
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_message),
        ]

        with provider_call("llm"):
            llm = get_llm(request_timeout=30.0, max_retries=1)
            response = llm.invoke(messages)

        content = response.content if hasattr(response, "content") else str(response)
        results = _parse_llm_response(content, request.targets)
        return RoutingPromptResponse(results=results)


department_routing_prompt_service = DepartmentRoutingPromptService()
