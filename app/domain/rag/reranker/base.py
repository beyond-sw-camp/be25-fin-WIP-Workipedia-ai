from abc import ABC, abstractmethod


class BaseReranker(ABC):
    @abstractmethod
    def rerank(self, query: str, documents: list[str], top_k: int) -> list[int]:
        """질문과 문서 목록을 받아 관련도 높은 순서로 인덱스를 반환한다."""
        pass
