from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    LOCAL = "local"            # Ollama, 온프레미스
    OPENAI = "openai"          # OpenAI 단독
    GOOGLE = "google"          # Google 단독
    ANTHROPIC = "anthropic"    # Anthropic 단독
    FALLBACK = "fallback"      # OpenAI → Google → Anthropic 순서로 자동 폴백


class EmbeddingProvider(str, Enum):
    LOCAL = "local"    # Ollama, 온프레미스
    OPENAI = "openai"
    GOOGLE = "google"


class Settings(BaseSettings):
    # Provider 선택
    llm_provider: LLMProvider = LLMProvider.LOCAL
    embedding_provider: EmbeddingProvider = EmbeddingProvider.LOCAL

    # 인프라 URL / Port
    ollama_base_url: str = "http://localhost:11434"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # API Keys (secrets)
    openai_api_key: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()

# ---------------------------------------------------------------------------
# LLM 모델명 매핑
# ---------------------------------------------------------------------------
CHAT_MODEL_MAP: dict[str, str] = {
    "local": "llama3.1:8b",
    "openai": "gpt-4o-mini",
    "google": "gemini-1.5-flash",
    "anthropic": "claude-haiku-4-5-20251001",
}

# ---------------------------------------------------------------------------
# Embedding 모델명 매핑 / 벡터 차원
# ---------------------------------------------------------------------------
EMBEDDING_MODEL_MAP: dict[str, str] = {
    "local": "bge-m3",
    "openai": "text-embedding-3-small",
    "google": "text-embedding-004",
}
EMBEDDING_DIM_MAP: dict[str, int] = {
    "local": 1024,    # bge-m3
    "openai": 1536,   # text-embedding-3-small
    "google": 768,    # text-embedding-004
}

# ---------------------------------------------------------------------------
# Vector Store collection 매핑
# ---------------------------------------------------------------------------
COLLECTION_MAP: dict[str, str] = {
    "MANUAL": "manual_chunks",
    "WORKI": "worki_chunks",
    "KNOWLEDGE_DATA": "knowledge_data_chunks",
    "MANUAL_KNOWLEDGE": "manual_knowledge_chunks",
}

# ---------------------------------------------------------------------------
# source_type별 청킹 파라미터
# ---------------------------------------------------------------------------
CHUNK_CONFIG: dict[str, dict[str, int]] = {
    "MANUAL": {"chunk_size": 500, "chunk_overlap": 100},
    "WORKI": {"chunk_size": 300, "chunk_overlap": 50},
    "KNOWLEDGE_DATA": {"chunk_size": 400, "chunk_overlap": 80},
    "MANUAL_KNOWLEDGE": {"chunk_size": 400, "chunk_overlap": 80},
}

# ---------------------------------------------------------------------------
# Masking 기본값
# ---------------------------------------------------------------------------
MASKING_ENABLED = True
MASKING_PHONE_ENABLED = False
MASKING_EMAIL_ENABLED = False

# ---------------------------------------------------------------------------
# RAG 파라미터
# ---------------------------------------------------------------------------
RETRIEVAL_TOP_K = 20
RERANK_TOP_K = 5
RERANKER_MODEL = "bongsoo/kpf-cross-encoder-v1"