import asyncio
import logging
import time
from typing import Protocol

from app.common.exceptions import ProviderError
from app.common.request_context import get_request_id
from app.core.config import COLLECTION_MAP, STEP_TIMEOUT, settings
from app.domain.chatbot.schemas import SessionMessage
from app.domain.rag.chain import RagChain
from app.domain.rag.schemas import OrchestratorResult, RagResult, RagStatus, StepRecord
from app.domain.rag.service import RagService
from app.domain.tool.chain import ToolResultChain
from app.domain.tool.selector import ToolSelector
from app.domain.tool.service import ToolService
from app.domain.tool.validator import InputValidator
from app.infra.tool.factory import get_tool_client

logger = logging.getLogger(__name__)


class StepRunner(Protocol):
    """폴백 체인의 각 단계가 구현해야 하는 인터페이스."""
    step_name: str
    timeout: float

    def run(
        self,
        query: str,
        retrieval_query: str,
        custom_prompt: str | None,
        session_context: list,
        caller_employee_id: str | None = None,
    ) -> RagResult:
        ...


# ── A단계: 매뉴얼 RAG ─────────────────────────────────────────────────────────

class ManualRagStep:
    step_name = "A"
    timeout = STEP_TIMEOUT["A"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(
        self,
        query: str,
        retrieval_query: str,
        custom_prompt: str | None,
        session_context: list[SessionMessage],
        caller_employee_id: str | None = None,
    ) -> RagResult:
        candidates = self._service.search_and_rerank(retrieval_query, COLLECTION_MAP["MANUAL"])
        result = self._chain.generate(query, candidates, custom_prompt, session_context)
        result.retrieval_top_score = self._service.last_retrieval_top_score
        result.retrieval_candidate_count = self._service.last_retrieval_candidate_count
        return result


# ── B단계: 워키 RAG ───────────────────────────────────────────────────────────

class WorkiRagStep:
    step_name = "B"
    timeout = STEP_TIMEOUT["B"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(
        self,
        query: str,
        retrieval_query: str,
        custom_prompt: str | None,
        session_context: list[SessionMessage],
        caller_employee_id: str | None = None,
    ) -> RagResult:
        candidates = self._service.search_and_rerank(retrieval_query, COLLECTION_MAP["WORKI"])
        result = self._chain.generate(query, candidates, custom_prompt, session_context)
        result.retrieval_top_score = self._service.last_retrieval_top_score
        result.retrieval_candidate_count = self._service.last_retrieval_candidate_count
        return result


# ── C단계: 지식 RAG ───────────────────────────────────────────────────────────

class KnowledgeRagStep:
    step_name = "C"
    timeout = STEP_TIMEOUT["C"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(
        self,
        query: str,
        retrieval_query: str,
        custom_prompt: str | None,
        session_context: list[SessionMessage],
        caller_employee_id: str | None = None,
    ) -> RagResult:
        candidates = self._service.search_knowledge(retrieval_query)
        result = self._chain.generate(query, candidates, custom_prompt, session_context)
        result.retrieval_top_score = self._service.last_retrieval_top_score
        result.retrieval_candidate_count = self._service.last_retrieval_candidate_count
        return result


# ── 문서 근거 통합 단계: 매뉴얼+워키+지식(A+B+C) ──────────────────────────────
# 폴백(A→B→C)이 아니라 세 출처 후보를 모두 합쳐 한 번 통합 reranking한 뒤
# 답변을 1회 생성한다. 매뉴얼과 워키 근거를 함께 인용하기 위함.

class DocumentRagStep:
    step_name = "DOC"
    timeout = STEP_TIMEOUT["DOC"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(
        self,
        query: str,
        retrieval_query: str,
        custom_prompt: str | None,
        session_context: list[SessionMessage],
        caller_employee_id: str | None = None,
    ) -> RagResult:
        candidates = self._service.search_evidence(retrieval_query)
        result = self._chain.generate(query, candidates, custom_prompt, session_context)
        result.retrieval_top_score = self._service.last_retrieval_top_score
        result.retrieval_candidate_count = self._service.last_retrieval_candidate_count
        return result


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

    def run(
        self,
        query: str,
        retrieval_query: str,
        custom_prompt: str | None,
        session_context: list[SessionMessage],
        caller_employee_id: str | None = None,
    ) -> RagResult:
        return self._service.run(query, retrieval_query, custom_prompt, session_context, caller_employee_id=caller_employee_id)


# ── 폴백 오케스트레이터 ────────────────────────────────────────────────────────

class RagOrchestrator:
    def __init__(self, steps: list | None = None) -> None:
        self._steps = steps if steps is not None else [
            # 매뉴얼+워키+지식을 하나의 통합 근거 단계로 묶고, 그 뒤 Tool(D)로 폴백한다.
            DocumentRagStep(), ToolCallingStep(),
        ]

    async def run(
        self,
        query: str,
        retrieval_query: str | None = None,
        custom_prompt: str | None = None,
        session_context: list[SessionMessage] | None = None,
        caller_employee_id: str | None = None,
    ) -> OrchestratorResult:
        if retrieval_query is None:
            retrieval_query = query
        if session_context is None:
            session_context = []

        history: list[StepRecord] = []
        orchestrator_started_at = time.perf_counter()
        for step in self._steps:
            started_at = time.perf_counter()
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(step.run, query, retrieval_query, custom_prompt, session_context, caller_employee_id),
                    timeout=step.timeout,
                )
            except asyncio.TimeoutError:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                logger.warning("[latency] request_id=%s step=%s status=TIMEOUT elapsed_ms=%.1f", get_request_id(), step.step_name, elapsed_ms)
                history.append(StepRecord(step=step.step_name, status=RagStatus.NO_RESULT, error_message="timeout"))
                if step.step_name == "D":
                    return OrchestratorResult(status=RagStatus.NO_RESULT, step_history=history, action="CREATE_TICKET")
                continue
            except ProviderError as exc:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                logger.warning("[latency] request_id=%s step=%s status=ERROR elapsed_ms=%.1f error=%s", get_request_id(), step.step_name, elapsed_ms, exc.message)
                status = RagStatus.NO_RESULT if step.step_name == "D" else RagStatus.ERROR
                history.append(StepRecord(step=step.step_name, status=status, error_message=exc.message))
                if step.step_name == "D":
                    return OrchestratorResult(status=RagStatus.NO_RESULT, step_history=history, action="CREATE_TICKET")
                continue

            elapsed_ms = (time.perf_counter() - started_at) * 1000
            logger.info(
                "[rag_route] request_id=%s step=%s status=%s route=%s action=%s elapsed_ms=%.1f",
                get_request_id(),
                step.step_name,
                result.status.value,
                step.step_name if result.status == RagStatus.SUCCESS else None,
                None,
                elapsed_ms,
            )
            if settings.latency_log_enabled:
                logger.info("[latency] request_id=%s step=%s status=%s elapsed_ms=%.1f", get_request_id(), step.step_name, result.status.value, elapsed_ms)
            history.append(StepRecord(
                step=step.step_name,
                status=result.status,
                error_message=result.error_message,
                retrieval_top_score=result.retrieval_top_score,
                retrieval_candidate_count=result.retrieval_candidate_count,
            ))

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
                return OrchestratorResult(status=RagStatus.NO_RESULT, step_history=history, action="CREATE_TICKET")
            # NO_RESULT (또는 A/B/C의 ERROR) → 다음 단계로 계속

        logger.info(
            "[rag_route] request_id=%s step=%s status=%s route=%s action=%s elapsed_ms=%.1f",
            get_request_id(),
            "-",
            RagStatus.NO_RESULT.value,
            None,
            "CREATE_TICKET",
            (time.perf_counter() - orchestrator_started_at) * 1000,
        )
        return OrchestratorResult(status=RagStatus.NO_RESULT, step_history=history, action="CREATE_TICKET")


rag_orchestrator = RagOrchestrator()
