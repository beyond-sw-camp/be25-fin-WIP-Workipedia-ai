from langchain_core.language_models import BaseChatModel

from app.core.config import LLMProvider, settings
from app.common.exceptions import ProviderError
from .base import BaseLLMClient
from .ollama_client import OllamaClient
from .openai_client import OpenAIClient


def get_llm_client() -> BaseLLMClient:
    if settings.llm_provider == LLMProvider.OPENAI:
        return OpenAIClient()
    if settings.llm_provider == LLMProvider.OLLAMA:
        return OllamaClient()
    raise ProviderError("llm", f"지원하지 않는 provider: {settings.llm_provider}")


def get_llm() -> BaseChatModel:
    """domain 코드에서 사용하는 단축 함수. provider 선택을 캡슐화한다."""
    return get_llm_client().get_model()
