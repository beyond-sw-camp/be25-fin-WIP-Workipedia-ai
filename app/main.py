from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.common.exceptions import WorkipediaException, workipedia_exception_handler

app = FastAPI(title="Workipedia AI Server")

app.include_router(v1_router)
app.add_exception_handler(WorkipediaException, workipedia_exception_handler)
