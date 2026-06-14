from langchain_ollama import ChatOllama
from langchain_core.language_models import BaseChatModel

from app.core.config import CHAT_MODEL_MAP, settings
from .base import BaseLLMClient


class OllamaClient(BaseLLMClient):
    def get_model(self, request_timeout: float | None = None, max_retries: int | None = None) -> BaseChatModel:
        kwargs = {
            "base_url": settings.ollama_base_url,
            "model": CHAT_MODEL_MAP["local"],
        }
        if request_timeout is not None:
            kwargs["client_kwargs"] = {"timeout": request_timeout}
            kwargs["async_client_kwargs"] = {"timeout": request_timeout}
        return ChatOllama(**kwargs)
