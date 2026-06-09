from langchain_community.chat_models import ChatOllama
from langchain_core.language_models import BaseChatModel

from app.core.config import settings
from .base import BaseLLMClient


class OllamaClient(BaseLLMClient):
    def get_model(self) -> BaseChatModel:
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.chat_model,
        )
