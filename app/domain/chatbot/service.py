import asyncio
import logging
import time
from typing import AsyncIterator

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.common.masking import StreamMasker, masker
from app.common.request_context import get_request_id
from app.core.config import STEP_TIMEOUT, settings
from app.domain.chatbot.contextualizer import contextualize
from app.domain.chatbot.no_result_policy import FALLBACK_DECISION, no_result_policy, should_precheck_general_chat
from app.domain.chatbot.schemas import SessionMessage
from app.domain.chatbot.stream import DoneEvent, ErrorEvent, StreamEvent, TokenEvent
from app.domain.rag import chain as rag_chain
from app.domain.rag.orchestrator import rag_orchestrator
from app.domain.rag.schemas import GeneratedAnswer, OrchestratorResult, RagStatus, StepRecord

logger = logging.getLogger(__name__)

_ERROR_MESSAGE = "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
_BLOCKED_MESSAGE = "요청을 처리할 수 없습니다."
_CREATE_TICKET_MESSAGE = "관련 문서를 찾지 못했어요. 티켓으로 문의할까요?"

_TICKET_CONFIRM_PROMPTS = (
    "티켓으로 문의할까요",
    "티켓을 발행할까요",
    "티켓으로 문의하시겠어요",
)
_AFFIRMATIVE_REPLIES = {
    "ㅇ",
    "ㅇㅇ",
    "응",
    "네",
    "예",
    "넵",
    "좋아",
    "그래",
    "어",
    "해주세요",
    "해줘",
    "발행해줘",
    "문의해줘",
    "티켓 발행해줘",
}
_NEGATIVE_REPLIES = {
    "ㄴ",
    "ㄴㄴ",
    "아니",
    "아니요",
    "괜찮아",
    "괜찮아요",
    "취소",
    "하지마",
    "안해",
}

def _has_document_candidates(result: OrchestratorResult) -> bool:
    for step in result.step_history:
        if step.step in {"A", "B", "C"} and (step.retrieval_top_score or 0.0) >= settings.rag_retrieval_score_threshold:
            return True
    return False


def _last_assistant_asked_ticket(context: list[SessionMessage]) -> bool:
    for msg in reversed(context):
        if msg.sender_type != "ASSISTANT":
            continue
        return any(prompt in msg.content for prompt in _TICKET_CONFIRM_PROMPTS)
    return False


def _normalize_reply(text: str) -> str:
    return text.strip().lower().rstrip(".!！?？~")


def _resolve_ticket_confirmation(question: str, context: list[SessionMessage]) -> OrchestratorResult | None:
    if not _last_assistant_asked_ticket(context):
        return None

    normalized = _normalize_reply(question)
    if normalized in _AFFIRMATIVE_REPLIES:
        return OrchestratorResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(answer="좋아요. 티켓을 발행할게요.", references=[]),
            route="CHAT",
            action="CREATE_TICKET",
        )
    if normalized in _NEGATIVE_REPLIES:
        return OrchestratorResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(answer="알겠어요. 티켓은 발행하지 않을게요.", references=[]),
            route="CHAT",
        )
    return None


class ChatbotService:
    async def _resolve_general_chat(self, question: str) -> OrchestratorResult | None:
        if not should_precheck_general_chat(question):
            return None

        started_at = time.perf_counter()
        try:
            decision = await asyncio.wait_for(
                asyncio.to_thread(no_result_policy.decide, question),
                timeout=settings.no_result_policy_timeout,
            )
        except asyncio.TimeoutError:
            decision = FALLBACK_DECISION
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning("no_result_policy precheck_intent=%s elapsed_ms=%.1f", decision.intent, elapsed_ms)

        if decision.intent != "GENERAL_CHAT":
            return None
        return OrchestratorResult(
            status=RagStatus.SUCCESS,
            answer=GeneratedAnswer(answer=decision.answer or "", references=[]),
            route="CHAT",
        )

    async def _apply_no_result_policy(self, question: str, result: OrchestratorResult) -> OrchestratorResult:
        if result.status != RagStatus.NO_RESULT or result.action != "CREATE_TICKET":
            return result

        started_at = time.perf_counter()
        try:
            decision = await asyncio.wait_for(
                asyncio.to_thread(no_result_policy.decide, question),
                timeout=settings.no_result_policy_timeout,
            )
        except asyncio.TimeoutError:
            decision = FALLBACK_DECISION
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        logger.warning("no_result_policy intent=%s elapsed_ms=%.1f", decision.intent, elapsed_ms)

        if decision.intent != "WORK_SUPPORT":
            return OrchestratorResult(
                status=RagStatus.SUCCESS,
                answer=GeneratedAnswer(answer=decision.answer or "", references=[]),
                route="CHAT",
                step_history=result.step_history,
            )

        if _has_document_candidates(result):
            return OrchestratorResult(
                status=RagStatus.SUCCESS,
                answer=GeneratedAnswer(
                    answer="문서에서 관련 후보는 찾았지만, 답변으로 확정할 만큼의 근거를 만들지 못했어요. 질문을 조금 더 구체적으로 바꿔 다시 물어봐 주세요.",
                    references=[],
                ),
                route="CHAT",
                step_history=result.step_history,
            )

        return result

    async def _prepare(
        self,
        question: str,
        session_context: list[SessionMessage] | None,
    ) -> tuple[str, list[SessionMessage], StepRecord | None]:
        """트리밍 + contextualize. 검색용 질의와 선택된 컨텍스트, CONTEXT 오류 기록을 반환한다."""
        if session_context is None:
            session_context = []

        max_n = settings.max_context_messages
        if max_n == 0:
            selected_context: list[SessionMessage] = []
        else:
            selected_context = session_context[-max_n:]

        context_record: StepRecord | None = None
        if max_n == 0 or not selected_context:
            retrieval_query = question
        else:
            try:
                _ctx_start = time.perf_counter()
                retrieval_query = await asyncio.wait_for(
                    asyncio.to_thread(contextualize, question, selected_context),
                    timeout=STEP_TIMEOUT["CONTEXT"],
                )
                if settings.latency_log_enabled:
                    logger.info("[latency] request_id=%s contextualize_ms=%.1f", get_request_id(), (time.perf_counter() - _ctx_start) * 1000)
            except (ProviderError, asyncio.TimeoutError) as exc:
                msg = exc.message if isinstance(exc, ProviderError) else "timeout"
                context_record = StepRecord(step="CONTEXT", status=RagStatus.ERROR, error_message=msg)
                logger.error("contextualize 실패: %s", msg)
                retrieval_query = question

        return retrieval_query, selected_context, context_record

    async def ask(
        self,
        question: str,
        custom_prompt: str | None = None,
        session_context: list[SessionMessage] | None = None,
        caller_employee_id: str | None = None,
    ) -> OrchestratorResult:
        followup_result = _resolve_ticket_confirmation(question, session_context or [])
        if followup_result is not None:
            return followup_result

        general_chat_result = await self._resolve_general_chat(question)
        if general_chat_result is not None:
            if general_chat_result.answer is not None:
                try:
                    general_chat_result.answer.answer = masker.mask(general_chat_result.answer.answer)
                except MaskingBlockedError:
                    return OrchestratorResult(status=RagStatus.BLOCKED, step_history=general_chat_result.step_history)
            return general_chat_result

        retrieval_query, selected_context, context_record = await self._prepare(question, session_context)

        # Orchestrator
        result = await rag_orchestrator.run(
            query=question,
            retrieval_query=retrieval_query,
            custom_prompt=custom_prompt,
            session_context=selected_context,
            caller_employee_id=caller_employee_id,
        )

        # 검색/도구 결과가 없을 때만 티켓 오발행 방지 정책 적용
        result = await self._apply_no_result_policy(question, result)

        # 출력 마스킹
        if result.answer is not None:
            try:
                result.answer.answer = masker.mask(result.answer.answer)
            except MaskingBlockedError:
                return OrchestratorResult(status=RagStatus.BLOCKED, step_history=result.step_history)

        # CONTEXT 오류 기록 병합
        if context_record is not None:
            result.step_history.insert(0, context_record)

        return result

    async def ask_stream(
        self,
        question: str,
        custom_prompt: str | None = None,
        session_context: list[SessionMessage] | None = None,
        caller_employee_id: str | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """2단계 스트리밍.

        stage 1: orchestrator로 SUCCESS·route·검증된 references를 확정한다(비스트리밍).
        stage 2: A/B/C는 references만 근거로 답변을 재생성하여 토큰 단위로 스트리밍하고,
                 D(Tool)는 references가 없으므로 stage 1의 마스킹된 답변을 그대로 흘린다.
        """
        followup_result = _resolve_ticket_confirmation(question, session_context or [])
        if followup_result is not None:
            if followup_result.answer and followup_result.answer.answer:
                yield TokenEvent(content=followup_result.answer.answer)
            yield DoneEvent(
                route=followup_result.route,
                action=followup_result.action,
                step_history=followup_result.step_history,
            )
            return

        general_chat_result = await self._resolve_general_chat(question)
        if general_chat_result is not None:
            try:
                answer = masker.mask(general_chat_result.answer.answer if general_chat_result.answer else "")
            except MaskingBlockedError:
                yield ErrorEvent(message=_BLOCKED_MESSAGE)
                return
            if answer:
                yield TokenEvent(content=answer)
            yield DoneEvent(route=general_chat_result.route, step_history=general_chat_result.step_history)
            return

        retrieval_query, selected_context, context_record = await self._prepare(question, session_context)

        result = await rag_orchestrator.run(
            query=question,
            retrieval_query=retrieval_query,
            custom_prompt=custom_prompt,
            session_context=selected_context,
            caller_employee_id=caller_employee_id,
        )

        step_history = list(result.step_history)
        if context_record is not None:
            step_history.insert(0, context_record)
        result.step_history = step_history
        result = await self._apply_no_result_policy(question, result)
        step_history = result.step_history

        if result.status == RagStatus.BLOCKED:
            yield ErrorEvent(message=_BLOCKED_MESSAGE)
            return
        if result.status == RagStatus.ERROR:
            yield ErrorEvent(message=_ERROR_MESSAGE)
            return
        if result.status != RagStatus.SUCCESS or result.answer is None:
            # NO_RESULT 등 — 본문 없이 전환 액션·이력만 전달한다.
            if result.action == "CREATE_TICKET":
                yield TokenEvent(content=_CREATE_TICKET_MESSAGE)
            yield DoneEvent(route=result.route, action=result.action, step_history=step_history)
            return

        references = result.answer.references
        produced = False

        if references:
            # stage 2: A/B/C — references만 근거로 재생성 스트리밍
            stream_masker = StreamMasker()
            try:
                async for text in rag_chain.stream_answer(
                    question, references, custom_prompt, selected_context
                ):
                    out = stream_masker.feed(text)
                    if out:
                        produced = True
                        yield TokenEvent(content=out)
                tail = stream_masker.flush()
                if tail:
                    produced = True
                    yield TokenEvent(content=tail)
            except MaskingBlockedError:
                yield ErrorEvent(message=_BLOCKED_MESSAGE)
                return
            except Exception as exc:  # 스트리밍 중 provider/네트워크 오류
                logger.error("스트리밍 답변 생성 실패: %s", exc)
                yield ErrorEvent(message=_ERROR_MESSAGE)
                return

        if not produced:
            # references 없음(D) 또는 재생성 결과가 비어 있음 → stage 1 답변을 마스킹해 전달
            try:
                fallback = masker.mask(result.answer.answer)
            except MaskingBlockedError:
                yield ErrorEvent(message=_BLOCKED_MESSAGE)
                return
            if fallback:
                yield TokenEvent(content=fallback)

        yield DoneEvent(references=references, route=result.route, action=result.action, step_history=step_history)


chatbot_service = ChatbotService()
