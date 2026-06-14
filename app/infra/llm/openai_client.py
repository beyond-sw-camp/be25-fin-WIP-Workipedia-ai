from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from app.core.config import CHAT_MODEL_MAP, settings
from .base import BaseLLMClient

_TIMEOUT = 60
_MAX_RETRIES = 2


class OpenAIClient(BaseLLMClient):
    def get_model(self, request_timeout: float | None = None) -> BaseChatModel:
        return ChatOpenAI(
            api_key=settings.openai_api_key,
            model=CHAT_MODEL_MAP["openai"],
            timeout=request_timeout if request_timeout is not None else _TIMEOUT,
            max_retries=_MAX_RETRIES,
        )
