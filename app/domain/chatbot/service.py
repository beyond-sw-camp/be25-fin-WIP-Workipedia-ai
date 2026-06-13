from app.domain.rag.orchestrator import rag_orchestrator
from app.domain.rag.schemas import OrchestratorResult


class ChatbotService:
    async def ask(self, question: str) -> OrchestratorResult:
        return await rag_orchestrator.run(question)


chatbot_service = ChatbotService()
