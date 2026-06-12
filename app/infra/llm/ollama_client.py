from langchain_community.chat_models import ChatOllama
from langchain_core.language_models import BaseChatModel

from app.core.config import CHAT_MODEL_MAP, settings
from .base import BaseLLMClient

_TIMEOUT = 60


class OllamaClient(BaseLLMClient):
    def get_model(self) -> BaseChatModel:
        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=CHAT_MODEL_MAP["local"],
            timeout=_TIMEOUT,
        )
