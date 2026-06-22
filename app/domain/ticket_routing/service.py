from dataclasses import dataclass, field

from app.core.config import (
    ROUTING_CASES_COLLECTION,
    ROUTING_DEPT_RR_COLLECTION,
    ROUTING_RERANK_TOP_K,
    ROUTING_RETRIEVAL_TOP_K,
    settings,
)
from app.domain.rag.retriever import rag_retriever
from app.domain.rag.schemas import RagCandidate
from app.domain.ticket_routing.schemas import (
    CandidateDepartment,
    TicketRoutingRequest,
    TicketRoutingResponse,
)
from app.common.exceptions import ProviderError, provider_call
from app.infra.embedding.factory import get_embeddings

ROUTING_MODEL = "embedding-similarity"
ROUTING_PROVIDER = "qdrant"


@dataclass
class _DeptGroup:
    department_id: int
    department_name: str
    rr_chunks: list[RagCandidate] = field(default_factory=list)
    case_chunks: list[RagCandidate] = field(default_factory=list)

    @property
    def max_score(self) -> float:
        all_chunks = self.rr_chunks + self.case_chunks
        return max(c.score for c in all_chunks) if all_chunks else 0.0

    def build_context(self) -> str:
        rr = sorted(self.rr_chunks, key=lambda c: c.score, reverse=True)[:1]
        cases = sorted(self.case_chunks, key=lambda c: c.score, reverse=True)[:3]
        return "\n".join(c.text for c in rr + cases)


def _common_queue(reasons: list[str], candidates: list[CandidateDepartment]) -> TicketRoutingResponse:
    return TicketRoutingResponse(
        assigned_department_id=None,
        assigned_department_name=None,
        confidence_score=None,
        score_margin=None,
        decision="COMMON_QUEUE",
        reasons=reasons,
        candidate_departments=candidates,
        model=ROUTING_MODEL,
        provider=ROUTING_PROVIDER,
    )


def _group_by_dept(candidates: list[RagCandidate]) -> dict[int, _DeptGroup]:
    groups: dict[int, _DeptGroup] = {}
    for c in candidates:
        dept_id = c.metadata.get("department_id")
        dept_name = c.metadata.get("department_name")
        if dept_id is None or dept_name is None:
            continue
        if dept_id not in groups:
            groups[dept_id] = _DeptGroup(department_id=dept_id, department_name=dept_name)
        chunk_type = c.metadata.get("type")
        if chunk_type == "rr":
            groups[dept_id].rr_chunks.append(c)
        elif chunk_type == "case":
            groups[dept_id].case_chunks.append(c)
    return groups


class TicketRoutingService:
    def recommend(self, request: TicketRoutingRequest) -> TicketRoutingResponse:
        query = f"{request.title}\n{request.content}"

        with provider_call("embedding"):
            embedding = get_embeddings().embed_query(query)

        try:
            rr_results = rag_retriever.search_by_embedding(
                embedding, ROUTING_DEPT_RR_COLLECTION, ROUTING_RETRIEVAL_TOP_K
            )
            case_results = rag_retriever.search_by_embedding(
                embedding, ROUTING_CASES_COLLECTION, ROUTING_RETRIEVAL_TOP_K
            )
        except ProviderError:
            return _common_queue(["라우팅 데이터 검색 중 오류가 발생해 공통 접수 큐로 이동합니다."], [])

        groups = _group_by_dept(rr_results + case_results)
        if not groups:
            return _common_queue(["부서 R&R·사례 데이터가 없어 공통 접수 큐로 이동합니다."], [])

        top_depts = sorted(groups.values(), key=lambda g: g.max_score, reverse=True)[:ROUTING_RERANK_TOP_K]

        candidate_list = [
            CandidateDepartment(
                department_id=g.department_id,
                department_name=g.department_name,
                confidence_score=g.max_score,
            )
            for g in top_depts
        ]

        if len(candidate_list) < 2:
            return _common_queue(["후보 부서가 1개뿐이어서 자동 배정하지 않습니다."], candidate_list)

        top_score = candidate_list[0].confidence_score
        score_margin = top_score - candidate_list[1].confidence_score

        score_ok = top_score >= settings.routing_score_threshold
        margin_ok = score_margin >= settings.routing_margin_threshold

        if score_ok and margin_ok:
            top = top_depts[0]
            return TicketRoutingResponse(
                assigned_department_id=top.department_id,
                assigned_department_name=top.department_name,
                confidence_score=top_score,
                score_margin=score_margin,
                decision="ASSIGNED",
                reasons=[f"유사도 점수({top_score:.3f})와 마진({score_margin:.3f})이 임계값을 초과해 자동 배정합니다."],
                candidate_departments=candidate_list,
                model=ROUTING_MODEL,
                provider=ROUTING_PROVIDER,
            )

        reasons: list[str] = []
        if not score_ok:
            reasons.append(f"유사도 점수({top_score:.3f})가 임계값({settings.routing_score_threshold})에 미달합니다.")
        if not margin_ok:
            reasons.append(f"1·2위 점수 차이({score_margin:.3f})가 임계값({settings.routing_margin_threshold})에 미달합니다.")

        return TicketRoutingResponse(
            assigned_department_id=None,
            assigned_department_name=None,
            confidence_score=top_score,
            score_margin=score_margin,
            decision="COMMON_QUEUE",
            reasons=reasons,
            candidate_departments=candidate_list,
            model=ROUTING_MODEL,
            provider=ROUTING_PROVIDER,
        )


ticket_routing_service = TicketRoutingService()
