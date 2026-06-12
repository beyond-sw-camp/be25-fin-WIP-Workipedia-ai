from langchain_openai import OpenAIEmbeddings
from langchain_core.embeddings import Embeddings

from app.core.config import EMBEDDING_MODEL_MAP, settings
from .base import BaseEmbeddingClient


class OpenAIEmbeddingClient(BaseEmbeddingClient):
    def get_embeddings(self) -> Embeddings:
        return OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            model=EMBEDDING_MODEL_MAP["openai"],
        )
