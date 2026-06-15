import asyncio
import logging

from app.common.exceptions import MaskingBlockedError, ProviderError
from app.common.masking import masker
from app.core.config import STEP_TIMEOUT, settings
from app.domain.chatbot.contextualizer import contextualize
from app.domain.chatbot.schemas import SessionMessage
from app.domain.rag.orchestrator import rag_orchestrator
from app.domain.rag.schemas import OrchestratorResult, RagStatus, StepRecord

logger = logging.getLogger(__name__)


class ChatbotService:
    async def ask(
        self,
        question: str,
        custom_prompt: str | None = None,
        session_context: list[SessionMessage] | None = None,
    ) -> OrchestratorResult:
        if session_context is None:
            session_context = []

        # 1. 트리밍
        max_n = settings.max_context_messages
        if max_n == 0:
            selected_context: list[SessionMessage] = []
        else:
            selected_context = session_context[-max_n:]

        # 2. Contextualize
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

        # 3. Orchestrator
        result = await rag_orchestrator.run(
            query=question,
            retrieval_query=retrieval_query,
            custom_prompt=custom_prompt,
            session_context=selected_context,
        )

        # 4. 출력 마스킹
        if result.answer is not None:
            try:
                result.answer.answer = masker.mask(result.answer.answer)
            except MaskingBlockedError:
                return OrchestratorResult(status=RagStatus.BLOCKED, step_history=result.step_history)

        # 5. CONTEXT 오류 기록 병합
        if context_record is not None:
            result.step_history.insert(0, context_record)

        return result


chatbot_service = ChatbotService()
