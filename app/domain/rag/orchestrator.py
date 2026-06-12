import asyncio
from typing import Protocol

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.common.masking import masker
from app.core.config import COLLECTION_MAP, STEP_TIMEOUT
from app.domain.rag.chain import RagChain
from app.domain.rag.schemas import OrchestratorResult, RagResult, RagStatus, StepRecord
from app.domain.rag.service import RagService


class StepRunner(Protocol):
    step_name: str
    timeout: float

    def run(self, query: str, custom_prompt: str | None) -> RagResult:
        ...


class ManualRagStep:
    step_name = "A"
    timeout = STEP_TIMEOUT["A"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(self, query: str, custom_prompt: str | None) -> RagResult:
        candidates = self._service.search_and_rerank(query, COLLECTION_MAP["MANUAL"])
        return self._chain.generate(query, candidates, custom_prompt)


class WorkiRagStep:
    step_name = "B"
    timeout = STEP_TIMEOUT["B"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(self, query: str, custom_prompt: str | None) -> RagResult:
        candidates = self._service.search_and_rerank(query, COLLECTION_MAP["WORKI"])
        return self._chain.generate(query, candidates, custom_prompt)


class KnowledgeRagStep:
    step_name = "C"
    timeout = STEP_TIMEOUT["C"]

    def __init__(self) -> None:
        self._service = RagService()
        self._chain = RagChain()

    def run(self, query: str, custom_prompt: str | None) -> RagResult:
        candidates = self._service.search_knowledge(query)
        return self._chain.generate(query, candidates, custom_prompt)


class ToolCallingStep:
    step_name = "D"
    timeout = STEP_TIMEOUT["D"]

    def run(self, query: str, custom_prompt: str | None) -> RagResult:
        # 이슈 #11에서 실제 Tool Calling 로직으로 교체
        return RagResult(status=RagStatus.NO_RESULT)


class RagOrchestrator:
    def __init__(self, steps: list | None = None) -> None:
        self._steps = steps if steps is not None else [
            ManualRagStep(), WorkiRagStep(), KnowledgeRagStep(), ToolCallingStep(),
        ]

    async def run(self, query: str, custom_prompt: str | None = None) -> OrchestratorResult:
        try:
            masked_query = masker.mask(query)
        except MaskingBlockedError:
            return OrchestratorResult(status=RagStatus.BLOCKED, step_history=[])

        history: list[StepRecord] = []
        for step in self._steps:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(step.run, masked_query, custom_prompt),
                    timeout=step.timeout,
                )
            except asyncio.TimeoutError:
                # soft timeout: thread continues — stop chain to prevent accumulation
                history.append(StepRecord(step=step.step_name, status=RagStatus.ERROR, error_message="timeout"))
                return OrchestratorResult(status=RagStatus.ERROR, step_history=history)
            except ProviderError as exc:
                history.append(StepRecord(step=step.step_name, status=RagStatus.ERROR, error_message=exc.message))
                continue
            # Other exceptions propagate → FastAPI 500

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

        return OrchestratorResult(status=RagStatus.NO_RESULT, step_history=history, action="CREATE_TICKET")


rag_orchestrator = RagOrchestrator()
