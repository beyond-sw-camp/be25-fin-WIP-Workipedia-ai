from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.embeddings import Embeddings

from app.core.config import EMBEDDING_MODEL_MAP, settings
from .base import BaseEmbeddingClient

_TIMEOUT = 30


class OllamaEmbeddingClient(BaseEmbeddingClient):
    def get_embeddings(self) -> Embeddings:
        return OllamaEmbeddings(
            base_url=settings.ollama_base_url,
            model=EMBEDDING_MODEL_MAP["ollama"],
            timeout=_TIMEOUT,
        )
