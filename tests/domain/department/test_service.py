from types import SimpleNamespace
from unittest.mock import patch

from app.domain.department.schemas import DepartmentTarget, RoutingPromptRequest
from app.domain.department.service import DepartmentRoutingPromptService


def test_generate_preserves_existing_prompt_when_instruction_adds_role():
    service = DepartmentRoutingPromptService()
    request = RoutingPromptRequest(
        instruction="개발 1팀은 RAG",
        targets=[
            DepartmentTarget(
                department_id=1,
                department_name="개발 1팀",
                current_prompt="개발 1팀은 챗봇 개발을 담당한다.",
            )
        ],
    )

    with patch("app.domain.department.service.get_llm") as mock_get_llm:
        mock_get_llm.return_value.invoke.return_value = SimpleNamespace(
            content='{"results":[{"departmentId":1,"routingPrompt":"개발 1팀은 RAG를 담당한다."}]}'
        )

        response = service.generate(request)

    assert len(response.results) == 1
    routing_prompt = response.results[0].routing_prompt
    assert "챗봇 개발" in routing_prompt
    assert "RAG" in routing_prompt


def test_generate_allows_replace_when_instruction_explicitly_replaces_role():
    service = DepartmentRoutingPromptService()
    request = RoutingPromptRequest(
        instruction="개발 1팀 역할을 RAG로 교체",
        targets=[
            DepartmentTarget(
                department_id=1,
                department_name="개발 1팀",
                current_prompt="개발 1팀은 챗봇 개발을 담당한다.",
            )
        ],
    )

    with patch("app.domain.department.service.get_llm") as mock_get_llm:
        mock_get_llm.return_value.invoke.return_value = SimpleNamespace(
            content='{"results":[{"departmentId":1,"routingPrompt":"개발 1팀은 RAG를 담당한다."}]}'
        )

        response = service.generate(request)

    assert response.results[0].routing_prompt == "개발 1팀은 RAG를 담당한다."
