from app.core.config import settings
from .base import BaseLLMClient
from .ollama_client import OllamaClient
from .openai_client import OpenAIClient


def get_llm_client() -> BaseLLMClient:
    if settings.llm_provider == "openai":
        return OpenAIClient()
    return OllamaClient()
