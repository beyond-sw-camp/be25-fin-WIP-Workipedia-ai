from langchain_core.language_models import BaseChatModel

from app.core.config import LLMProvider, settings
from app.common.exceptions import ProviderError
from .ollama_client import OllamaClient
from .openai_client import OpenAIClient
from .google_client import GoogleClient
from .anthropic_client import AnthropicClient

# rate limit·타임아웃·서버 오류에만 폴백하고, 인증 오류(4xx)는 폴백하지 않는다.
_FALLBACK_EXCEPTIONS = (Exception,)


def get_llm(request_timeout: float | None = None, max_retries: int | None = None) -> BaseChatModel:
    """domain 코드에서 사용하는 단축 함수. provider 선택을 캡슐화한다.

    LOCAL: Ollama (온프레미스)
    FALLBACK: OpenAI 실패 시 Google, Google 실패 시 Anthropic 순으로 자동 전환
    """
    if settings.llm_provider == LLMProvider.LOCAL:
        return OllamaClient().get_model(request_timeout, max_retries)

    if settings.llm_provider == LLMProvider.OPENAI:
        return OpenAIClient().get_model(request_timeout, max_retries)

    if settings.llm_provider == LLMProvider.GOOGLE:
        return GoogleClient().get_model(request_timeout, max_retries)

    if settings.llm_provider == LLMProvider.ANTHROPIC:
        return AnthropicClient().get_model(request_timeout, max_retries)

    if settings.llm_provider == LLMProvider.FALLBACK:
        candidates = []
        if settings.openai_api_key:
            candidates.append(OpenAIClient().get_model(request_timeout, max_retries))
        if settings.google_api_key:
            candidates.append(GoogleClient().get_model(request_timeout, max_retries))
        if settings.anthropic_api_key:
            candidates.append(AnthropicClient().get_model(request_timeout, max_retries))
        if not candidates:
            raise ProviderError("llm", "FALLBACK 모드에 사용 가능한 API 키가 없습니다.")
        if len(candidates) == 1:
            return candidates[0]
        return candidates[0].with_fallbacks(
            candidates[1:],
            exceptions_to_handle=_FALLBACK_EXCEPTIONS,
        )

    raise ProviderError("llm", f"지원하지 않는 provider: {settings.llm_provider}")
