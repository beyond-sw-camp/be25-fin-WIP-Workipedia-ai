import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.api.v1.router import router as v1_router
from app.common.exceptions import WorkipediaException, workipedia_exception_handler


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.domain.rag.reranker.cross_encoder_reranker import get_reranker
    get_reranker()
    yield


app = FastAPI(title="Workipedia AI Server", lifespan=lifespan)


@app.middleware("http")
async def add_response_time_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    response.headers["X-Response-Time"] = f"{elapsed:.3f}s"
    return response


app.include_router(v1_router)
app.add_exception_handler(WorkipediaException, workipedia_exception_handler)
