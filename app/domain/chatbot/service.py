import asyncio
import logging
from typing import AsyncIterator

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.common.masking import StreamMasker, masker
from app.core.config import STEP_TIMEOUT, settings
from app.domain.chatbot.contextualizer import contextualize
from app.domain.chatbot.schemas import SessionMessage
from app.domain.chatbot.stream import DoneEvent, ErrorEvent, StreamEvent, TokenEvent
from app.domain.rag import chain as rag_chain
from app.domain.rag.orchestrator import rag_orchestrator
from app.domain.rag.schemas import OrchestratorResult, RagStatus, StepRecord

logger = logging.getLogger(__name__)

_ERROR_MESSAGE = "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
_BLOCKED_MESSAGE = "요청을 처리할 수 없습니다."


class ChatbotService:
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
                retrieval_query = await asyncio.wait_for(
                    asyncio.to_thread(contextualize, question, selected_context),
                    timeout=STEP_TIMEOUT["CONTEXT"],
                )
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
    ) -> OrchestratorResult:
        retrieval_query, selected_context, context_record = await self._prepare(question, session_context)

        # Orchestrator
        result = await rag_orchestrator.run(
            query=question,
            retrieval_query=retrieval_query,
            custom_prompt=custom_prompt,
            session_context=selected_context,
        )

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
    ) -> AsyncIterator[StreamEvent]:
        """2단계 스트리밍.

        stage 1: orchestrator로 SUCCESS·route·검증된 references를 확정한다(비스트리밍).
        stage 2: A/B/C는 references만 근거로 답변을 재생성하여 토큰 단위로 스트리밍하고,
                 D(Tool)는 references가 없으므로 stage 1의 마스킹된 답변을 그대로 흘린다.
        """
        retrieval_query, selected_context, context_record = await self._prepare(question, session_context)

        result = await rag_orchestrator.run(
            query=question,
            retrieval_query=retrieval_query,
            custom_prompt=custom_prompt,
            session_context=selected_context,
        )

        step_history = list(result.step_history)
        if context_record is not None:
            step_history.insert(0, context_record)

        if result.status == RagStatus.BLOCKED:
            yield ErrorEvent(message=_BLOCKED_MESSAGE)
            return
        if result.status == RagStatus.ERROR:
            yield ErrorEvent(message=_ERROR_MESSAGE)
            return
        if result.status != RagStatus.SUCCESS or result.answer is None:
            # NO_RESULT 등 — 본문 없이 전환 액션·이력만 전달한다.
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

        yield DoneEvent(references=references, route=result.route, step_history=step_history)


chatbot_service = ChatbotService()
