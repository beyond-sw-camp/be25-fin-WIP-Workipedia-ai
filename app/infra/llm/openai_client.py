from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from app.core.config import settings
from .base import BaseLLMClient


class OpenAIClient(BaseLLMClient):
    def get_model(self) -> BaseChatModel:
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=settings.openai_chat_model,
        )
