from langchain_core.embeddings import Embeddings

from app.core.config import EmbeddingProvider, settings
from app.common.exceptions import ProviderError, provider_call
from .base import BaseEmbeddingClient
from .ollama_embedding import OllamaEmbeddingClient
from .openai_embedding import OpenAIEmbeddingClient
from .google_embedding import GoogleEmbeddingClient


def get_embedding_client() -> BaseEmbeddingClient:
    if settings.embedding_provider == EmbeddingProvider.OLLAMA:
        return OllamaEmbeddingClient()
    if settings.embedding_provider == EmbeddingProvider.OPENAI:
        return OpenAIEmbeddingClient()
    if settings.embedding_provider == EmbeddingProvider.GOOGLE:
        return GoogleEmbeddingClient()
    raise ProviderError("embedding", f"지원하지 않는 provider: {settings.embedding_provider}")


def get_embeddings() -> Embeddings:
    """domain 코드에서 사용하는 단축 함수. provider 선택을 캡슐화한다."""
    return get_embedding_client().get_embeddings()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """텍스트 목록을 임베딩 벡터로 변환한다. 빈 입력은 ProviderError를 발생시킨다."""
    if not texts:
        raise ProviderError("embedding", "임베딩 대상 텍스트가 없습니다.")
    non_empty = [t for t in texts if t and t.strip()]
    if not non_empty:
        raise ProviderError("embedding", "모든 텍스트가 비어 있습니다.")
    with provider_call("embedding"):
        return get_embeddings().embed_documents(non_empty)
