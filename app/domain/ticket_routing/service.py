from dataclasses import dataclass, field

from app.core.config import (
    RERANKER_MODEL,
    ROUTING_CASES_COLLECTION,
    ROUTING_DEPT_RR_COLLECTION,
    ROUTING_RERANK_TOP_K,
    ROUTING_RETRIEVAL_TOP_K,
    settings,
)
from app.domain.rag.reranker.cross_encoder_reranker import get_reranker
from app.domain.rag.retriever import rag_retriever
from app.domain.rag.schemas import RagCandidate
from app.domain.ticket_routing.schemas import (
    CandidateDepartment,
    TicketRoutingRequest,
    TicketRoutingResponse,
)
from app.common.exceptions import ProviderError, provider_call
from app.infra.embedding.factory import get_embeddings


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
        model=RERANKER_MODEL,
        provider="cross-encoder",
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
        chunk_type = c.metadata.get("type", "")
        if chunk_type == "rr":
            groups[dept_id].rr_chunks.append(c)
        else:
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

        dept_candidates = [
            RagCandidate(
                candidate_id=f"department-{g.department_id}",
                text=g.build_context(),
                score=g.max_score,
                metadata={"department_id": g.department_id, "department_name": g.department_name},
            )
            for g in top_depts
        ]

        try:
            reranked = get_reranker().rerank(
                query=query,
                candidates=dept_candidates,
                top_k=len(dept_candidates),
            )
        except ProviderError:
            return _common_queue(["Cross-Encoder 오류로 공통 접수 큐로 이동합니다."], [])

        candidate_list = [
            CandidateDepartment(
                department_id=r.metadata["department_id"],
                department_name=r.metadata["department_name"],
                confidence_score=r.score,
            )
            for r in reranked
        ]

        if len(reranked) < 2:
            return _common_queue(["후보 부서가 1개뿐이어서 자동 배정하지 않습니다."], candidate_list)

        top_score = reranked[0].score
        score_margin = reranked[0].score - reranked[1].score

        if top_score < settings.routing_score_threshold:
            return _common_queue(
                [f"1위 점수 {top_score:.2f}가 기준({settings.routing_score_threshold})에 미달합니다."],
                candidate_list,
            )

        if score_margin < settings.routing_margin_threshold:
            return _common_queue(
                [f"1·2위 점수 차 {score_margin:.2f}가 기준({settings.routing_margin_threshold})에 미달합니다."],
                candidate_list,
            )

        top = reranked[0]
        return TicketRoutingResponse(
            assigned_department_id=top.metadata["department_id"],
            assigned_department_name=top.metadata["department_name"],
            confidence_score=top_score,
            score_margin=score_margin,
            decision="AUTO_ASSIGNED",
            reasons=[f"1위 점수 {top_score:.2f}, 1·2위 점수 차 {score_margin:.2f}로 자동 배정 기준 통과"],
            candidate_departments=candidate_list,
            model=RERANKER_MODEL,
            provider="cross-encoder",
        )


ticket_routing_service = TicketRoutingService()
