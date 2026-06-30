from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    LOCAL = "local"            # Ollama, 온프레미스
    OPENAI = "openai"          # OpenAI 단독
    GOOGLE = "google"          # Google 단독
    ANTHROPIC = "anthropic"    # Anthropic 단독
    FALLBACK = "fallback"      # OpenAI → Google → Anthropic 순서로 자동 폴백 - 로컬


class EmbeddingProvider(str, Enum):
    LOCAL = "local"    # Ollama, 온프레미스
    E5 = "e5"          # sentence-transformers multilingual-e5-base
    OPENAI = "openai"
    GOOGLE = "google"


class Settings(BaseSettings):
    # Provider 선택
    llm_provider: LLMProvider = LLMProvider.LOCAL
    embedding_provider: EmbeddingProvider = EmbeddingProvider.LOCAL

    # Tool Calling
    tool_client: str = "stub"           # "stub" | "workipedia"
    be_base_url: str = "http://localhost:8080"
    internal_api_key: str = ""          # BE InternalApiKeyFilter와 동일한 값이어야 한다 (X-Internal-Api-Key)
    tool_http_timeout: float = 25.0     # D단계 전체 timeout보다 짧게
    max_context_messages: int = Field(default=10, ge=0)
    contextualize_llm_timeout: float = Field(default=25.0, gt=0, lt=30.0)
    no_result_policy_timeout: float = Field(default=5.0, gt=0, lt=30.0)
    rag_answer_llm_timeout: float = Field(default=8.0, gt=0, lt=30.0)
    rag_retrieval_score_threshold: float = Field(default=0.50, ge=0.0)
    rag_reranker_enabled: bool = True

    # 인프라 URL / Port
    ollama_base_url: str = "http://localhost:11434"
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # API Keys (secrets)
    openai_api_key: str = ""
    google_api_key: str = ""
    anthropic_api_key: str = ""

    # 티켓 부서 라우팅 임계값 (환경변수로 재배포 없이 조정 가능)
    # Cross-Encoder(kpf) 재정렬 점수 스케일 기준값. 깨끗한 R&R 기준 정답 부서 점수 0.06~0.22, 마진 0.04~0.20 관측.
    # ⚠️ 임시값 — 실제 티켓으로 재튜닝 필요.
    routing_score_threshold: float = 0.05
    routing_margin_threshold: float = 0.03
    routing_single_score_threshold: float = 0.05

    # RAG 단계별 latency 로깅 on/off
    latency_log_enabled: bool = True

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
    "e5": "intfloat/multilingual-e5-base",
    "openai": "text-embedding-3-small",
    "google": "text-embedding-004",
}
EMBEDDING_DIM_MAP: dict[str, int] = {
    "local": 1024,    # bge-m3
    "e5": 768,        # intfloat/multilingual-e5-base
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
RERANK_TOP_K = 6
# 근거 통합 검색에서 각 출처(매뉴얼/워키/지식)의 검색(코사인) 상위 N개는
# Cross-Encoder 재정렬 결과와 무관하게 최종 후보에 반드시 포함한다.
# Cross-Encoder가 특정 출처를 과소평가해 답변 근거에서 누락되는 것을 방지하기 위함.
# 0이면 출처 보장 없이 순수 통합 reranking 순서만 사용한다.
RERANK_PER_SOURCE_MIN = 1
RERANKER_MODEL = "bongsoo/kpf-cross-encoder-v1"
# Cross-Encoder가 가장 관련 있다고 판단한 1위 문서의 최소 통과 점수.
# 이 점수는 0~1 확률이 아니라 모델의 raw logit이므로 0.0이 관련도 0%라는 뜻은 아니다.
# 1위 점수가 0.0 미만이면 근거가 부족하다고 보고 답변을 생성하지 않고 NO_RESULT를 반환한다.
# 현재 0.0은 평가셋 확보 전 임시 기준이며, 실제 질문/문서 평가 결과에 따라 조정해야 한다.
RERANK_SCORE_THRESHOLD = 0.0

# ---------------------------------------------------------------------------
# 티켓 부서 라우팅 파라미터
# ---------------------------------------------------------------------------
ROUTING_RETRIEVAL_TOP_K = 20
ROUTING_RERANK_TOP_K = 3
ROUTING_DEPT_RR_COLLECTION = "routing_dept_rr"
ROUTING_CASES_COLLECTION = "routing_cases"
KNOWLEDGE_SYNC_CONFIG: dict[str, dict[str, str]] = {
    "DEPT_RR": {
        "collection": ROUTING_DEPT_RR_COLLECTION,
        "type": "rr",
    },
    "ROUTING_CASE": {
        "collection": ROUTING_CASES_COLLECTION,
        "type": "case",
    },
}

# ---------------------------------------------------------------------------
# 폴백 단계별 timeout (초)
# ---------------------------------------------------------------------------
STEP_TIMEOUT: dict[str, float] = {
    "CONTEXT": 30.0,
    "A": 30.0,
    "B": 30.0,
    "C": 30.0,
    "D": 60.0,
    # DOC: 매뉴얼+워키+지식 통합 근거 검색·통합 reranking·답변 생성 한 단계
    "DOC": 45.0,
}
