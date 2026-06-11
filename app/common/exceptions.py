from contextlib import contextmanager
from typing import Generator

from fastapi import Request
from fastapi.responses import JSONResponse


class WorkipediaException(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message


class ProviderError(Exception):
    """LLM·Embedding provider 호출 실패. orchestrator에서 ERROR 단계로 처리한다."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        self.message = message
        super().__init__(f"[{provider}] {message}")


class MaskingBlockedError(Exception):
    """민감정보 마스킹 실패. orchestrator에서 BLOCKED 상태로 처리한다."""


@contextmanager
def provider_call(provider: str) -> Generator[None, None, None]:
    """provider 호출을 감싸서 모든 예외를 ProviderError로 변환한다."""
    try:
        yield
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(provider, str(exc)) from exc


async def workipedia_exception_handler(request: Request, exc: WorkipediaException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.message},
    )
