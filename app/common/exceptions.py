from fastapi import Request
from fastapi.responses import JSONResponse


class WorkipediaException(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message


async def workipedia_exception_handler(request: Request, exc: WorkipediaException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.message},
    )
