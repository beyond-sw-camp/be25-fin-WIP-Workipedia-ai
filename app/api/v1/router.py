from fastapi import APIRouter

from app.api.v1.endpoints import health, chatbot, department, documents, embeddings, ticket_routing, ticket_draft, knowledge_sync, manual_summary

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(chatbot.router)
router.include_router(documents.router)
router.include_router(embeddings.router)
router.include_router(ticket_routing.router)
router.include_router(ticket_draft.router)
router.include_router(knowledge_sync.router)
router.include_router(department.router)
router.include_router(manual_summary.router)
