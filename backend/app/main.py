from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.activity import router as activity_router
from app.api.chat import passage_router
from app.api.chat import router as chat_router
from app.api.documents import router as documents_router
from app.config import settings

structlog.configure(processors=[structlog.processors.JSONRenderer()])
logger = structlog.get_logger()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(passage_router)
app.include_router(activity_router)


@app.middleware("http")
async def log_request(request: Request, call_next):
    response = await call_next(request)
    logger.info(
        "request_completed",
        request_id=uuid4().hex,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
    )
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
