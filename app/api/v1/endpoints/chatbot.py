from fastapi import APIRouter

from app.domain.chatbot.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chatbot"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    # TODO: ChatbotService 연결
    return ChatResponse(answer="준비 중입니다.", sources=[], route=None)
