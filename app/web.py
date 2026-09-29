"""Browser-facing service for the existing Agent. Run with uvicorn app.web:app."""

from dataclasses import replace
from contextlib import asynccontextmanager
from hmac import compare_digest
import logging
import os
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from deepseek_harness import DeepSeekHarness

from app.agent import create_harness
from app.config import AgentConfig


logger = logging.getLogger(__name__)
_run_lock = Lock()
_index = Path(__file__).parent / "static" / "index.html"
_chat_patch = Path(__file__).parent / "web_chat.patch.yml"
_harness: DeepSeekHarness | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _harness
    yield
    with _run_lock:
        if _harness is not None:
            _harness.close()
            _harness = None


app = FastAPI(title="Agent Base", docs_url=None, redoc_url=None, lifespan=lifespan)


def _get_harness(config: AgentConfig) -> DeepSeekHarness:
    global _harness
    if _harness is None:
        candidate = create_harness(config)
        try:
            candidate.start()
        except Exception:
            candidate.close()
            raise
        _harness = candidate
    return _harness


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息不能为空")
        return value


class ChatResponse(BaseModel):
    answer: str
    session_id: str


def _check_access_token(provided: str | None) -> None:
    expected = os.getenv("SERVICE_ACCESS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="服务尚未配置访问口令")
    if not provided or not compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="访问口令错误")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_index, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest, x_access_token: str | None = Header(default=None)) -> ChatResponse:
    global _harness
    config = AgentConfig.load()  # Also loads local .env without overriding host secrets.
    _check_access_token(x_access_token)
    if not config.has_api_key:
        raise HTTPException(status_code=503, detail="服务尚未配置 DeepSeek API Key")
    config = replace(
        config,
        profile="sdk-minimal",
        workspace=config.workspace.parent / "workspace-web",
        harness_home=config.harness_home.parent / ".harness-web",
        patches=(_chat_patch.as_posix(),),
    )

    session_id = body.session_id or uuid4().hex
    try:
        # The SDK writes to one Harness home, so runs are serialized in this process.
        with _run_lock:
            result = _get_harness(config).run(body.message, session_id=session_id)
    except Exception:
        logger.exception("Harness request failed")
        with _run_lock:
            if _harness is not None:
                try:
                    _harness.close()
                except Exception:
                    logger.exception("Failed to close Harness after request error")
                finally:
                    _harness = None
        raise HTTPException(status_code=502, detail="Agent 调用失败，请检查服务日志") from None

    if result.finish_reason != "completed":
        logger.error("Harness turn ended with reason: %s", result.finish_reason)
        raise HTTPException(status_code=502, detail="Agent 未完成本轮请求，请检查模型连接和服务日志")
    answer = (result.final_response or "").strip()
    if not answer:
        raise HTTPException(status_code=502, detail="Agent 没有返回文字")
    return ChatResponse(answer=answer, session_id=session_id)
