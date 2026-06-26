import asyncio
from unittest.mock import MagicMock

import pytest
from app.domain.chatbot.schemas import SessionMessage
from app.domain.rag.schemas import OrchestratorResult, RagResult, RagStatus


def _msg(mid, role, content):
    return SessionMessage(message_id=mid, sender_type=role, content=content)


@pytest.mark.asyncio
async def test_orchestrator_passes_retrieval_query_to_step():
    from app.domain.rag.orchestrator import RagOrchestrator

    step = MagicMock()
    step.step_name = "A"
    step.timeout = 5.0
    step.run.return_value = RagResult(status=RagStatus.SUCCESS,
                                      answer=MagicMock(references=[]))

    orch = RagOrchestrator(steps=[step])
    await orch.run(
        query="며칠 전에?",
        retrieval_query="연차 신청 며칠 전에?",
        custom_prompt=None,
        session_context=[],
    )
    step.run.assert_called_once_with("며칠 전에?", "연차 신청 며칠 전에?", None, [])


@pytest.mark.asyncio
async def test_orchestrator_does_not_mask_internally():
    from app.domain.rag.orchestrator import RagOrchestrator

    step = MagicMock()
    step.step_name = "A"
    step.timeout = 5.0
    received = []

    def capture_run(query, retrieval_query, custom_prompt, session_context):
        received.append((query, retrieval_query))
        return RagResult(status=RagStatus.SUCCESS, answer=MagicMock(references=[]))

    step.run.side_effect = capture_run

    orch = RagOrchestrator(steps=[step])
    await orch.run(
        query="이미 마스킹됨",
        retrieval_query="이미 마스킹됨 검색용",
        custom_prompt=None,
        session_context=[],
    )
    assert received[0] == ("이미 마스킹됨", "이미 마스킹됨 검색용")
