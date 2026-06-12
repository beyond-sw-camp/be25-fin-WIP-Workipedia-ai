from typing import Protocol

from app.core.config import COLLECTION_MAP, STEP_TIMEOUT
from app.domain.rag.chain import RagChain
from app.domain.rag.schemas import RagResult, RagStatus
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
