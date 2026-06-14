import asyncio
from typing import Protocol

from app.common.exceptions import ProviderError
from app.core.config import COLLECTION_MAP, STEP_TIMEOUT
from app.domain.chatbot.schemas import SessionMessage
from app.domain.rag.chain import RagChain
from app.domain.rag.schemas import OrchestratorResult, RagResult, RagStatus, StepRecord
from app.domain.rag.service import RagService
from app.domain.tool.chain import ToolResultChain
from app.domain.tool.selector import ToolSelector
from app.domain.tool.service import ToolService
from app.domain.tool.validator import InputValidator
from app.infra.tool.factory import get_tool_client


class StepRunner(Protocol):
    """폴백 체인의 각 단계가 구현해야 하는 인터페이스."""
    step_name: str
    timeout: float

    def run(self, query: str, retrieval_query: str, custom_prompt: str | None, session_context: list) -> RagResult:
        ...


# ── A단계: 매뉴얼 RAG ─────────────────────────────────────────────────────────

class ManualRagStep:
    step_name = "A"
    timeout = STEP_TIMEOUT["A"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(self, query: str, retrieval_query: str, custom_prompt: str | None, session_context: list[SessionMessage]) -> RagResult:
        candidates = self._service.search_and_rerank(retrieval_query, COLLECTION_MAP["MANUAL"])
        return self._chain.generate(query, candidates, custom_prompt, session_context)


# ── B단계: 워키 RAG ───────────────────────────────────────────────────────────

class WorkiRagStep:
    step_name = "B"
    timeout = STEP_TIMEOUT["B"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(self, query: str, retrieval_query: str, custom_prompt: str | None, session_context: list[SessionMessage]) -> RagResult:
        candidates = self._service.search_and_rerank(retrieval_query, COLLECTION_MAP["WORKI"])
        return self._chain.generate(query, candidates, custom_prompt, session_context)


# ── C단계: 지식 RAG ───────────────────────────────────────────────────────────

class KnowledgeRagStep:
    step_name = "C"
    timeout = STEP_TIMEOUT["C"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(self, query: str, retrieval_query: str, custom_prompt: str | None, session_context: list[SessionMessage]) -> RagResult:
        candidates = self._service.search_knowledge(retrieval_query)
        return self._chain.generate(query, candidates, custom_prompt, session_context)


# ── D단계: Tool Calling ───────────────────────────────────────────────────────

class ToolCallingStep:
    step_name = "D"
    timeout = STEP_TIMEOUT["D"]

    def __init__(self, service: ToolService | None = None) -> None:
        self._service = service or ToolService(
            client=get_tool_client(),
            selector=ToolSelector(),
            validator=InputValidator(),
            result_chain=ToolResultChain(),
        )

    def run(self, query: str, retrieval_query: str, custom_prompt: str | None, session_context: list[SessionMessage]) -> RagResult:
        return self._service.run(query, retrieval_query, custom_prompt, session_context)


# ── 폴백 오케스트레이터 ────────────────────────────────────────────────────────

class RagOrchestrator:
    def __init__(self, steps: list | None = None) -> None:
        self._steps = steps if steps is not None else [
            ManualRagStep(), WorkiRagStep(), KnowledgeRagStep(), ToolCallingStep(),
        ]

    async def run(
        self,
        query: str,
        retrieval_query: str | None = None,
        custom_prompt: str | None = None,
        session_context: list[SessionMessage] | None = None,
    ) -> OrchestratorResult:
        if retrieval_query is None:
            retrieval_query = query
        if session_context is None:
            session_context = []

        history: list[StepRecord] = []
        for step in self._steps:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(step.run, query, retrieval_query, custom_prompt, session_context),
                    timeout=step.timeout,
                )
            except asyncio.TimeoutError:
                history.append(StepRecord(step=step.step_name, status=RagStatus.ERROR, error_message="timeout"))
                return OrchestratorResult(status=RagStatus.ERROR, step_history=history)
            except ProviderError as exc:
                history.append(StepRecord(step=step.step_name, status=RagStatus.ERROR, error_message=exc.message))
                if step.step_name == "D":
                    return OrchestratorResult(status=RagStatus.ERROR, step_history=history)
                continue

            history.append(StepRecord(step=step.step_name, status=result.status, error_message=result.error_message))

            if result.status == RagStatus.SUCCESS:
                return OrchestratorResult(
                    status=RagStatus.SUCCESS,
                    answer=result.answer,
                    route=step.step_name,
                    step_history=history,
                )
            if result.status == RagStatus.BLOCKED:
                return OrchestratorResult(status=RagStatus.BLOCKED, step_history=history)
            if result.status == RagStatus.ERROR and step.step_name == "D":
                return OrchestratorResult(status=RagStatus.ERROR, step_history=history)
            # NO_RESULT (또는 A/B/C의 ERROR) → 다음 단계로 계속

        return OrchestratorResult(status=RagStatus.NO_RESULT, step_history=history, action="CREATE_TICKET")


rag_orchestrator = RagOrchestrator()
