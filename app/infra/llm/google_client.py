from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models import BaseChatModel

from app.core.config import CHAT_MODEL_MAP, settings
from .base import BaseLLMClient

_TIMEOUT = 60
_MAX_RETRIES = 2


class GoogleClient(BaseLLMClient):
    def get_model(self, request_timeout: float | None = None, max_retries: int | None = None) -> BaseChatModel:
        return ChatGoogleGenerativeAI(
            google_api_key=settings.google_api_key,
            model=CHAT_MODEL_MAP["google"],
            timeout=request_timeout if request_timeout is not None else _TIMEOUT,
            max_retries=max_retries if max_retries is not None else _MAX_RETRIES,
        )
