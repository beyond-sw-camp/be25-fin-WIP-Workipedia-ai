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
    mock_service = MagicMock()
    mock_service.run.return_value = RagResult(status=RagStatus.NO_RESULT)
    step = ToolCallingStep(service=mock_service)
    assert step.step_name == "D"
    result = step.run("질문", "질문", None, [])
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
        result = step.run("매뉴얼 질문", "매뉴얼 질문 검색용", "custom", [])

    MockService.return_value.search_and_rerank.assert_called_once()
    call_args = MockService.return_value.search_and_rerank.call_args
    assert call_args[0][0] == "매뉴얼 질문 검색용"
    assert "manual_chunks" in call_args[0][1]
    MockChain.return_value.generate.assert_called_once_with("매뉴얼 질문", candidates, "custom", [])
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
        result = step.run("지식 질문", "지식 질문 검색용", None, [])

    MockService.return_value.search_knowledge.assert_called_once_with("지식 질문 검색용")
    assert result is expected


# ── Task 4: RagOrchestrator ────────────────────────────────────────────────


def _make_step(name: str, result: RagResult) -> MagicMock:
    step = MagicMock()
    step.step_name = name
    step.timeout = 5.0
    step.run.return_value = result
    return step


# ── 마스킹 ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_steps_returns_create_ticket():
    from app.domain.rag.orchestrator import RagOrchestrator
    orch = RagOrchestrator(steps=[])
    result = await orch.run("질문")
    assert result.status == RagStatus.NO_RESULT
    assert result.action == "CREATE_TICKET"


# ── SUCCESS ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_success_on_first_step():
    from app.domain.rag.orchestrator import RagOrchestrator

    step_a = _make_step("A", RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))
    step_b = _make_step("B", RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))

    orch = RagOrchestrator(steps=[step_a, step_b])
    result = await orch.run("질문")

    assert result.status == RagStatus.SUCCESS
    assert result.route == "A"
    assert len(result.step_history) == 1
    step_b.run.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_to_second_step():
    from app.domain.rag.orchestrator import RagOrchestrator

    step_a = _make_step("A", RagResult(status=RagStatus.NO_RESULT))
    step_b = _make_step("B", RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))

    orch = RagOrchestrator(steps=[step_a, step_b])
    result = await orch.run("질문")

    assert result.status == RagStatus.SUCCESS
    assert result.route == "B"
    assert len(result.step_history) == 2


# ── BLOCKED ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_blocked_stops_chain():
    from app.domain.rag.orchestrator import RagOrchestrator

    step_a = _make_step("A", RagResult(status=RagStatus.BLOCKED))
    step_b = _make_step("B", RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))

    orch = RagOrchestrator(steps=[step_a, step_b])
    result = await orch.run("질문")

    assert result.status == RagStatus.BLOCKED
    assert len(result.step_history) == 1
    step_b.run.assert_not_called()


# ── ERROR ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provider_error_continues_to_next():
    from app.domain.rag.orchestrator import RagOrchestrator
    from app.common.exceptions import ProviderError

    step_a = _make_step("A", RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))
    step_a.run.side_effect = ProviderError("llm", "timeout")
    step_b = _make_step("B", RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))

    orch = RagOrchestrator(steps=[step_a, step_b])
    result = await orch.run("질문")

    assert result.status == RagStatus.SUCCESS
    assert result.route == "B"
    assert result.step_history[0].status == RagStatus.ERROR
    assert result.step_history[0].error_message is not None


@pytest.mark.asyncio
async def test_all_steps_fail_returns_create_ticket():
    from app.domain.rag.orchestrator import RagOrchestrator

    steps = [
        _make_step("A", RagResult(status=RagStatus.NO_RESULT)),
        _make_step("B", RagResult(status=RagStatus.NO_RESULT)),
        _make_step("C", RagResult(status=RagStatus.NO_RESULT)),
        _make_step("D", RagResult(status=RagStatus.NO_RESULT)),
    ]

    orch = RagOrchestrator(steps=steps)
    result = await orch.run("해결 안 되는 질문")

    assert result.status == RagStatus.NO_RESULT
    assert result.action == "CREATE_TICKET"
    assert len(result.step_history) == 4


# ── TIMEOUT ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_stops_chain_immediately():
    from app.domain.rag.orchestrator import RagOrchestrator
    import asyncio

    async def slow_run():
        await asyncio.sleep(10)
        return RagResult(status=RagStatus.SUCCESS, answer=_make_answer())

    step_a = MagicMock()
    step_a.step_name = "A"
    step_a.timeout = 0.01  # 10ms — 의도적 timeout
    step_a.run = MagicMock(side_effect=lambda q, rq, p, sc: __import__('time').sleep(1) or RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))

    step_b = _make_step("B", RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))

    orch = RagOrchestrator(steps=[step_a, step_b])
    result = await orch.run("질문")

    assert result.status == RagStatus.ERROR
    assert result.step_history[0].error_message == "timeout"
    step_b.run.assert_not_called()


# ── 예상치 못한 예외 전파 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unexpected_exception_propagates():
    from app.domain.rag.orchestrator import RagOrchestrator

    step_a = _make_step("A", RagResult(status=RagStatus.SUCCESS, answer=_make_answer()))
    step_a.run.side_effect = RuntimeError("unexpected bug")

    orch = RagOrchestrator(steps=[step_a])

    with pytest.raises(RuntimeError, match="unexpected bug"):
        await orch.run("질문")


# ── 기본 단계 초기화 ────────────────────────────────────────────────────────────

def test_default_steps_are_four():
    from app.domain.rag.orchestrator import RagOrchestrator, ManualRagStep, WorkiRagStep, KnowledgeRagStep, ToolCallingStep

    with (
        patch("app.domain.rag.orchestrator.RagService"),
        patch("app.domain.rag.orchestrator.RagChain"),
        patch("app.domain.rag.reranker.cross_encoder_reranker.get_reranker"),
    ):
        orch = RagOrchestrator()

    assert len(orch._steps) == 4
    assert isinstance(orch._steps[0], ManualRagStep)
    assert isinstance(orch._steps[1], WorkiRagStep)
    assert isinstance(orch._steps[2], KnowledgeRagStep)
    assert isinstance(orch._steps[3], ToolCallingStep)


# ── D단계 ToolCallingStep 관련 테스트 ─────────────────────────────────────────

async def test_d_stage_no_result_falls_through_to_create_ticket():
    """D단계 NO_RESULT → CREATE_TICKET 액션 반환."""
    from app.domain.rag.orchestrator import RagOrchestrator

    no_result_step = MagicMock()
    no_result_step.step_name = "D"
    no_result_step.timeout = 10.0
    no_result_step.run.return_value = RagResult(status=RagStatus.NO_RESULT)

    orch = RagOrchestrator(steps=[no_result_step])
    result = await orch.run("질문")

    assert result.status == RagStatus.NO_RESULT
    assert result.action == "CREATE_TICKET"


async def test_d_stage_error_returns_error_immediately():
    """D단계 RagResult(ERROR) → 오케스트레이터가 즉시 ERROR 반환 (CREATE_TICKET 아님)."""
    from app.domain.rag.orchestrator import RagOrchestrator

    error_step = MagicMock()
    error_step.step_name = "D"
    error_step.timeout = 10.0
    error_step.run.return_value = RagResult(status=RagStatus.ERROR)

    orch = RagOrchestrator(steps=[error_step])
    result = await orch.run("질문")

    assert result.status == RagStatus.ERROR
    assert result.action is None


async def test_d_stage_provider_error_returns_error_immediately():
    """D단계 ProviderError → 오케스트레이터가 즉시 ERROR 반환 (CREATE_TICKET 아님)."""
    from app.domain.rag.orchestrator import RagOrchestrator
    from app.common.exceptions import ProviderError

    error_step = MagicMock()
    error_step.step_name = "D"
    error_step.timeout = 10.0
    error_step.run.side_effect = ProviderError("tool", "BE 연결 실패")

    orch = RagOrchestrator(steps=[error_step])
    result = await orch.run("질문")

    assert result.status == RagStatus.ERROR


async def test_abc_stage_error_continues_to_next_step():
    """A/B/C 단계 ERROR는 다음 단계로 폴백한다 (기존 동작 보호)."""
    from app.domain.rag.orchestrator import RagOrchestrator

    error_step = MagicMock()
    error_step.step_name = "A"
    error_step.timeout = 10.0
    error_step.run.return_value = RagResult(status=RagStatus.ERROR)

    success_step = MagicMock()
    success_step.step_name = "B"
    success_step.timeout = 10.0
    success_step.run.return_value = RagResult(
        status=RagStatus.SUCCESS,
        answer=GeneratedAnswer(answer="답변", references=[]),
    )

    orch = RagOrchestrator(steps=[error_step, success_step])
    result = await orch.run("질문")

    assert result.status == RagStatus.SUCCESS
