from app.core.config import settings
from .base import BaseEmbeddingClient
from .ollama_embedding import OllamaEmbeddingClient
from .openai_embedding import OpenAIEmbeddingClient


def get_embedding_client() -> BaseEmbeddingClient:
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingClient()
    return OllamaEmbeddingClient()
