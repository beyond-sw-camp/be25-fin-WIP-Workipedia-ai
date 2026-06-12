import asyncio
from unittest.mock import MagicMock, patch

import pytest

from app.domain.rag.schemas import (
    GeneratedAnswer,
    OrchestratorResult,
    RagResult,
    RagStatus,
    RerankedCandidate,
    StepRecord,
)


# ── 헬퍼 ──────────────────────────────────────────────────────────────────

def _make_answer() -> GeneratedAnswer:
    return GeneratedAnswer(
        answer="답변입니다.",
        references=[RerankedCandidate(candidate_id="MANUAL:1:0", text="내용", score=1.0, rank=1)],
    )


def _make_step(name: str, status: RagStatus, answer: GeneratedAnswer | None = None) -> MagicMock:
    step = MagicMock()
    step.step_name = name
    step.timeout = 10.0
    step.run.return_value = RagResult(status=status, answer=answer)
    return step


# ── Task 1: 스키마 타입 확인 ────────────────────────────────────────────────

def test_step_record_fields():
    record = StepRecord(step="A", status=RagStatus.SUCCESS)
    assert record.step == "A"
    assert record.status == RagStatus.SUCCESS
    assert record.error_message is None


def test_orchestrator_result_fields():
    result = OrchestratorResult(status=RagStatus.NO_RESULT, action="CREATE_TICKET", step_history=[])
    assert result.status == RagStatus.NO_RESULT
    assert result.action == "CREATE_TICKET"
    assert result.route is None
    assert result.answer is None


# ── Task 3: 단계 클래스 ────────────────────────────────────────────────────

def test_manual_rag_step_name():
    from app.domain.rag.orchestrator import ManualRagStep
    step = ManualRagStep()
    assert step.step_name == "A"


def test_worki_rag_step_name():
    from app.domain.rag.orchestrator import WorkiRagStep
    step = WorkiRagStep()
    assert step.step_name == "B"


def test_knowledge_rag_step_name():
    from app.domain.rag.orchestrator import KnowledgeRagStep
    step = KnowledgeRagStep()
    assert step.step_name == "C"


def test_tool_calling_step_returns_no_result():
    from app.domain.rag.orchestrator import ToolCallingStep
    step = ToolCallingStep()
    assert step.step_name == "D"
    result = step.run("질문", None)
    assert result.status == RagStatus.NO_RESULT


def test_manual_rag_step_delegates_to_service_and_chain():
    from app.domain.rag.orchestrator import ManualRagStep
    from app.domain.rag.schemas import RagResult, RagStatus

    candidates = [RerankedCandidate(candidate_id="MANUAL:1:0", text="내용", score=1.0, rank=1)]
    expected = RagResult(status=RagStatus.SUCCESS, answer=_make_answer())

    with (
        patch("app.domain.rag.orchestrator.RagService") as MockService,
        patch("app.domain.rag.orchestrator.RagChain") as MockChain,
    ):
        MockService.return_value.search_and_rerank.return_value = candidates
        MockChain.return_value.generate.return_value = expected

        step = ManualRagStep()
        result = step.run("매뉴얼 질문", "custom")

    MockService.return_value.search_and_rerank.assert_called_once()
    call_args = MockService.return_value.search_and_rerank.call_args
    assert call_args[0][0] == "매뉴얼 질문"
    assert "manual_chunks" in call_args[0][1]
    MockChain.return_value.generate.assert_called_once_with("매뉴얼 질문", candidates, "custom")
    assert result is expected


def test_knowledge_rag_step_uses_search_knowledge():
    from app.domain.rag.orchestrator import KnowledgeRagStep

    candidates = [RerankedCandidate(candidate_id="KNOWLEDGE_DATA:1:0", text="내용", score=1.0, rank=1)]
    expected = RagResult(status=RagStatus.SUCCESS, answer=_make_answer())

    with (
        patch("app.domain.rag.orchestrator.RagService") as MockService,
        patch("app.domain.rag.orchestrator.RagChain") as MockChain,
    ):
        MockService.return_value.search_knowledge.return_value = candidates
        MockChain.return_value.generate.return_value = expected

        step = KnowledgeRagStep()
        result = step.run("지식 질문", None)

    MockService.return_value.search_knowledge.assert_called_once_with("지식 질문")
    assert result is expected
