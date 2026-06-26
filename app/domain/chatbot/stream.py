from dataclasses import dataclass, field

from app.domain.rag.schemas import RerankedCandidate, StepRecord

# 스트리밍 챗봇 응답에서 흘려보내는 내부 이벤트.
# API 계층(SSE 엔드포인트)이 이 이벤트를 직렬화한다.


@dataclass
class TokenEvent:
    """마스킹이 끝난 답변 본문 조각."""
    content: str


@dataclass
class DoneEvent:
    """스트림 정상 종료. 출처·라우트·전환 액션·단계 이력을 담는다."""
    references: list[RerankedCandidate] = field(default_factory=list)
    route: str | None = None
    action: str | None = None
    step_history: list[StepRecord] = field(default_factory=list)


@dataclass
class ErrorEvent:
    """스트림 비정상 종료. 사용자에게 보여줄 안전한 메시지만 담는다."""
    message: str


StreamEvent = TokenEvent | DoneEvent | ErrorEvent
