from fastapi import APIRouter

from app.api.v1.endpoints import health, chatbot, documents, embeddings

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(chatbot.router)
router.include_router(documents.router)
router.include_router(embeddings.router)
