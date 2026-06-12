from dataclasses import dataclass, field
from enum import Enum


@dataclass
class RagCandidate:
    candidate_id: str
    text: str
    score: float
    metadata: dict = field(default_factory=dict)


@dataclass
class RerankedCandidate:
    candidate_id: str
    text: str
    score: float
    rank: int
    metadata: dict = field(default_factory=dict)
    retrieval_score: float = 0.0


class RagStatus(str, Enum):
    SUCCESS = "SUCCESS"
    NO_RESULT = "NO_RESULT"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"


@dataclass
class GeneratedAnswer:
    answer: str
    references: list[RerankedCandidate]  # cited_ids에 해당하는 후보만, 중복 제거


@dataclass
class RagResult:
    status: RagStatus
    answer: GeneratedAnswer | None = None
    error_message: str | None = None


@dataclass
class StepRecord:
    step: str
    status: RagStatus
    error_message: str | None = None


@dataclass
class OrchestratorResult:
    status: RagStatus
    answer: GeneratedAnswer | None = None
    route: str | None = None
    step_history: list[StepRecord] = field(default_factory=list)
    action: str | None = None
