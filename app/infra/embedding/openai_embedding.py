from langchain_openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings

from app.core.config import settings
from .base import BaseEmbeddingClient


class OpenAIEmbeddingClient(BaseEmbeddingClient):
    def get_embeddings(self) -> Embeddings:
        return OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
