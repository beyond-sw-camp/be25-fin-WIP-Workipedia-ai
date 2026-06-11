from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"


class EmbeddingProvider(str, Enum):
    OLLAMA = "ollama"
    OPENAI = "openai"


class Settings(BaseSettings):
    # LLM
    llm_provider: LLMProvider = LLMProvider.OLLAMA
    ollama_base_url: str = "http://localhost:11434"
    chat_model: str = "llama3.1:8b"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"

    # Embedding
    embedding_provider: EmbeddingProvider = EmbeddingProvider.OLLAMA
    embedding_model: str = "bge-m3"
    openai_embedding_model: str = "text-embedding-3-small"

    # Vector Store
    chroma_host: str = "localhost"
    chroma_port: int = 8001
    chroma_collection_name: str = "workipedia"

    # RAG
    retrieval_top_k: int = 20
    rerank_top_k: int = 5
    reranker_model: str = "bongsoo/kpf-cross-encoder-v1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
