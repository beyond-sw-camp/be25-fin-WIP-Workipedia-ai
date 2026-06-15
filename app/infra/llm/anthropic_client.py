from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from app.core.config import CHAT_MODEL_MAP, settings
from .base import BaseLLMClient

_TIMEOUT = 60
_MAX_RETRIES = 2


class AnthropicClient(BaseLLMClient):
    def get_model(self, request_timeout: float | None = None, max_retries: int | None = None) -> BaseChatModel:
        return ChatAnthropic(
            api_key=settings.anthropic_api_key,
            model=CHAT_MODEL_MAP["anthropic"],
            timeout=request_timeout if request_timeout is not None else _TIMEOUT,
            max_retries=max_retries if max_retries is not None else _MAX_RETRIES,
        )
