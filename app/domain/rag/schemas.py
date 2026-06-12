from dataclasses import dataclass, field


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
