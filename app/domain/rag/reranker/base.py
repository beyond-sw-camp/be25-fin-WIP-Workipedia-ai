from abc import ABC, abstractmethod

from app.domain.rag.schemas import RagCandidate, RerankedCandidate


class BaseReranker(ABC):
    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[RagCandidate],
        top_k: int,
    ) -> list[RerankedCandidate]:
        """질문과 후보 목록을 받아 재정렬된 RerankedCandidate 목록을 반환한다."""
        pass
