from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.common.exceptions import WorkipediaException, workipedia_exception_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.domain.rag.reranker.cross_encoder_reranker import get_reranker
    get_reranker()
    yield


app = FastAPI(title="Workipedia AI Server", lifespan=lifespan)

app.include_router(v1_router)
app.add_exception_handler(WorkipediaException, workipedia_exception_handler)
