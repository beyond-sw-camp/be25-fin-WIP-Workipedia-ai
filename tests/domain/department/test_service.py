from types import SimpleNamespace
from unittest.mock import patch

from app.domain.department.schemas import DepartmentTarget, RoutingPromptRequest
from app.domain.department.service import DepartmentRoutingPromptService


def _generate(current_prompt: str, llm_routing_prompt: str, instruction: str = "지시"):
    service = DepartmentRoutingPromptService()
    request = RoutingPromptRequest(
        instruction=instruction,
        targets=[
            DepartmentTarget(
                department_id=1,
                department_name="개발 1팀",
                current_prompt=current_prompt,
            )
        ],
    )
    with patch("app.domain.department.service.get_llm") as mock_get_llm:
        mock_get_llm.return_value.invoke.return_value = SimpleNamespace(
            content=f'{{"results":[{{"departmentId":1,"routingPrompt":"{llm_routing_prompt}"}}]}}'
        )
        return service.generate(request)


def test_generate_returns_llm_merged_prompt_verbatim():
    # LLM이 현재 역할 + 지시를 병합해 반환하면 코드가 다시 합치지 않고 그대로 사용한다.
    response = _generate("챗봇 개발을 담당한다.", "챗봇 개발과 RAG를 담당한다.")
    assert response.results[0].routing_prompt == "챗봇 개발과 RAG를 담당한다."


def test_generate_does_not_duplicate_when_llm_merges():
    # 회귀: 단어가 바뀌어 옛 문장을 글자 그대로 포함하지 않아도, 옛 문장을 중복 첨부하지 않는다.
    response = _generate("구매를 담당한다.", "구매와 연말정산을 담당한다.")
    routing_prompt = response.results[0].routing_prompt
    assert routing_prompt == "구매와 연말정산을 담당한다."
    assert routing_prompt.count("담당한다") == 1


def test_generate_replace_is_handled_by_llm():
    # 교체/대체는 LLM이 처리한다 — 코드가 별도로 분기하지 않고 LLM 결과를 그대로 반영한다.
    response = _generate("챗봇 개발을 담당한다.", "RAG를 담당한다.", instruction="역할을 RAG로 교체")
    assert response.results[0].routing_prompt == "RAG를 담당한다."
