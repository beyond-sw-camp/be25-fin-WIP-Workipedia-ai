from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_core.embeddings import Embeddings

from app.core.config import EMBEDDING_MODEL_MAP, settings
from .base import BaseEmbeddingClient


class GoogleEmbeddingClient(BaseEmbeddingClient):
    def get_embeddings(self) -> Embeddings:
        return GoogleGenerativeAIEmbeddings(
            google_api_key=settings.google_api_key,
            model=EMBEDDING_MODEL_MAP["google"],
        )
