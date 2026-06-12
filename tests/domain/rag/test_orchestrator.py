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
