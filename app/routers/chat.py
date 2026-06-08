from fastapi import APIRouter
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    # TODO: 폴백 체인 연결 (RAG → Function Calling → Ticket)
    return ChatResponse(
        answer="준비 중입니다.",
        sources=[],
        route=None,
    )
