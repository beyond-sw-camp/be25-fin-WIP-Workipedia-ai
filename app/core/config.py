from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM
    llm_provider: str = "ollama"  # ollama | openai
    ollama_base_url: str = "http://localhost:11434"
    chat_model: str = "llama3.1:8b"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"

    # Embedding
    embedding_provider: str = "ollama"  # ollama | openai
    embedding_model: str = "bge-m3"
    openai_embedding_model: str = "text-embedding-3-small"

    # Vector Store
    chroma_persist_path: str = ".chroma"
    chroma_collection_name: str = "workipedia"

    # RAG
    retrieval_top_k: int = 20
    rerank_top_k: int = 5
    reranker_model: str = "bongsoo/kpf-cross-encoder-v1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
