from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.embeddings import Embeddings

from app.core.config import settings
from .base import BaseEmbeddingClient

_TIMEOUT = 30


class OllamaEmbeddingClient(BaseEmbeddingClient):
    def get_embeddings(self) -> Embeddings:
        return OllamaEmbeddings(
            base_url=settings.ollama_base_url,
            model=settings.embedding_model,
            timeout=_TIMEOUT,
        )
