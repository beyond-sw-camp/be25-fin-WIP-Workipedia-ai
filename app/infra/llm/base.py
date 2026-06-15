from abc import ABC, abstractmethod
from langchain_core.language_models import BaseChatModel


class BaseLLMClient(ABC):
    @abstractmethod
    def get_model(self, request_timeout: float | None = None, max_retries: int | None = None) -> BaseChatModel:
        pass
