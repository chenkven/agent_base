"""Browser-facing service for the existing Agent. Run with uvicorn app.web:app."""

import asyncio
from dataclasses import replace
from contextlib import asynccontextmanager
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
import re
from threading import Event, Lock, Timer
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from deepseek_harness import DeepSeekHarness
from deepseek_harness.errors import JsonRpcError

from app.agent import create_harness
from app.config import AgentConfig
from app.engines import (
    DEFAULT_ENGINE_ID, bind_session_engine, configure_web_engine, get_engine,
    list_engines as list_dsh_engines,
)
from app.permissions import (
    check_database_ready,
    check_or_create_session,
    create_login,
    delete_chat,
    delete_user,
    list_chats,
    list_messages,
    list_users,
    register_user,
    resolve_login,
    reset_user_password,
    revoke_login,
    save_message,
    set_user_enabled,
    Principal,
)
from app.rate_limit import SharedLoginRateLimiter
from app.extensions import prepare_capabilities
from app.demo_mcp import demo_mcp
from app.trace import summarize_run_events
from app.platform import (
    bind_session_agent, get_agent, list_agents, list_grants, list_models,
    require_model, set_agent, set_agent_grant, set_model,
    list_capabilities, set_capability, set_agent_capability,
    list_agent_capability_ids,
)
from app.user_capabilities import (
    effective_capabilities, list_own_capabilities, set_own_capability,
    delete_own_capability, list_own_assignments, set_own_assignment,
    list_user_mcps, set_user_mcp_approval,
)
from app.workflows import (
    delete_workflow, get_run as get_workflow_run, get_workflow,
    list_runs as list_workflow_runs, list_workflows, save_workflow,
)
from app.workflow_runner import execute_workflow


logger = logging.getLogger(__name__)
_locks_guard = Lock()
_user_locks: dict[str, Lock] = {}
_harnesses_guard = Lock()
_login_limiter = SharedLoginRateLimiter()
_admission_guard = Lock()
_active_chat_users: set[str] = set()
_MAX_ACTIVE_CHATS = 8
_index = Path(__file__).parent / "static" / "index.html"
_login = Path(__file__).parent / "static" / "login.html"
_workflows_page = Path(__file__).parent / "static" / "workflows.html"
_engines_page = Path(__file__).parent / "static" / "engines.html"
_static = Path(__file__).parent / "static"
_chat_patch = Path(__file__).parent / "web_chat.patch.yml"
_providers_patch = Path(__file__).parent / "web_providers.patch.yml"
_harnesses: dict[str, DeepSeekHarness] = {}
_harness_settings_hashes: dict[str, str] = {}
_runtime_sessions: dict[tuple[str, str], str] = {}
_model_id_pattern = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_session_id_pattern = re.compile(r"[0-9a-f]{32}\Z")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Login and chat admission touch MySQL before their route-level config load.
    # Load .env once at startup so a cached browser bootstrap cannot skip it.
    AgentConfig.load()
    async with demo_mcp.session_manager.run():
        try:
            yield
        finally:
            await asyncio.to_thread(_close_all_harnesses)


app = FastAPI(title="Agent Base", docs_url=None, redoc_url=None, lifespan=lifespan)


class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            # URLs carry an asset version; repeat visits can skip tunnel round trips.
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response


app.mount("/static", CachedStaticFiles(directory=_static), name="static")
app.mount("/internal", demo_mcp.streamable_http_app())


def _get_user_lock(user_id: str) -> Lock:
    with _locks_guard:
        return _user_locks.setdefault(user_id, Lock())


def _admit_chat(user_id: str) -> None:
    with _admission_guard:
        if user_id in _active_chat_users:
            raise HTTPException(status_code=429, detail="当前账号已有消息正在处理，请稍后再试")
        if len(_active_chat_users) >= _MAX_ACTIVE_CHATS:
            raise HTTPException(status_code=503, detail="服务当前繁忙，请稍后再试")
        _active_chat_users.add(user_id)


def _release_chat_slot(user_id: str) -> None:
    with _admission_guard:
        _active_chat_users.discard(user_id)


def _chat_timeout_seconds() -> float:
    raw = os.getenv("WEB_CHAT_TIMEOUT_SECONDS", "180")
    try:
        seconds = float(raw)
    except ValueError:
        raise HTTPException(status_code=503, detail="聊天超时配置无效") from None
    if not 1 <= seconds <= 3600:
        raise HTTPException(status_code=503, detail="聊天超时需在 1 到 3600 秒之间")
    return seconds


def _call_harness_with_deadline(harness: DeepSeekHarness, call, deadline: float):
    expired = Event()

    def stop_harness() -> None:
        expired.set()
        try:
            harness.close()  # SDK close terminates its runtime and wakes the blocked run.
        except Exception:
            logger.exception("Failed to close timed-out Harness")

    remaining = deadline - monotonic()
    if remaining <= 0:
        stop_harness()
        raise HTTPException(status_code=504, detail="Agent 运行超时，请重试或开始新会话")
    watchdog = Timer(remaining, stop_harness)
    watchdog.daemon = True
    watchdog.start()
    try:
        try:
            result = call()
        except Exception:
            if expired.is_set():
                raise HTTPException(status_code=504, detail="Agent 运行超时，请重试或开始新会话") from None
            raise
        if expired.is_set():
            raise HTTPException(status_code=504, detail="Agent 运行超时，请重试或开始新会话")
        return result
    finally:
        watchdog.cancel()
        if expired.is_set():
            watchdog.join(timeout=5)


def _close_all_harnesses() -> None:
    with _harnesses_guard:
        user_ids = list(_harnesses)
    for user_id in user_ids:
        with _get_user_lock(user_id):
            _release_harness(user_id)


def _release_harness(user_id: str) -> None:
    # Call while holding this user's lock; the guard only protects shared maps.
    with _harnesses_guard:
        harness = _harnesses.pop(user_id, None)
        _harness_settings_hashes.pop(user_id, None)
        for key in [key for key in _runtime_sessions if key[0] == user_id]:
            _runtime_sessions.pop(key, None)
    if harness is not None:
        harness.close()


def _get_harness(
    config: AgentConfig, user_id: str, *, api_key: str | None = None,
    provider: str = "deepseek-official", model: str | None = None,
    agent_id: str = "default",
    capabilities_hash: str = "",
    new_session: bool = False, deadline: float | None = None,
) -> DeepSeekHarness:
    settings_hash = sha256(
        f"{config.profile}\0{config.dsh_bin}\0{config.harness_home}\0"
        f"{agent_id}\0{capabilities_hash}\0{provider}\0{model or config.model}\0{api_key or ''}".encode()
    ).hexdigest()
    with _harnesses_guard:
        harness = _harnesses.get(user_id)
        current_hash = _harness_settings_hashes.get(user_id)
    if harness is not None and current_hash != settings_hash:
        if not new_session:
            raise HTTPException(status_code=409, detail="模型或 API Key 已更换，请点击“新会话”再发送")
        _release_harness(user_id)
        harness = None
    if harness is None:
        options = {"provider": provider, "model": model, "isolate_other_keys": True}
        if api_key:
            options["api_key"] = api_key
        candidate = create_harness(config, **options)
        try:
            if deadline is None:
                candidate.start()
            else:
                _call_harness_with_deadline(candidate, candidate.start, deadline)
        except Exception:
            try:
                candidate.close()
            except Exception:
                logger.exception("Failed to close Harness after startup error")
            raise
        with _harnesses_guard:
            _harnesses[user_id] = candidate
            _harness_settings_hashes[user_id] = settings_hash
        harness = candidate
    return harness


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    api_key: str | None = None
    provider: str = "deepseek-official"
    model: str | None = None
    agent_id: str = "default"
    engine_id: str = DEFAULT_ENGINE_ID

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
    engine_id: str = DEFAULT_ENGINE_ID
    available_tools: list[str] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class ResetPasswordRequest(BaseModel):
    password: str


class UserStatusRequest(BaseModel):
    enabled: bool


class ModelSetting(BaseModel):
    enabled: bool = True
    user_enabled: bool = True


class AgentSetting(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    instructions: str = Field(default="", max_length=8000)
    delegate_id: str | None = None
    enabled: bool = True


class AgentGrant(BaseModel):
    granted: bool


class CapabilitySetting(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=80)
    content: str = Field(default="", max_length=16000)
    endpoint: str = Field(default="", max_length=2048)
    enabled: bool = True


class CapabilityAssignment(BaseModel):
    assigned: bool


class McpApproval(BaseModel):
    approved: bool


class WorkflowDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    engine_id: str = DEFAULT_ENGINE_ID
    steps: list[dict] = Field(min_length=1, max_length=8)


class WorkflowRunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    provider: str = "deepseek-official"
    model: str
    api_key: str | None = None


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_login, headers={"Cache-Control": "no-store"})


@app.get("/app", include_in_schema=False)
def chat_page() -> FileResponse:
    return FileResponse(_index, headers={"Cache-Control": "no-store"})


@app.get("/workflows", include_in_schema=False)
def workflows_page() -> FileResponse:
    return FileResponse(_workflows_page, headers={"Cache-Control": "no-store"})


@app.get("/engines", include_in_schema=False)
def engines_page() -> FileResponse:
    return FileResponse(_engines_page, headers={"Cache-Control": "no-store"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, str]:
    AgentConfig.load()  # Load local .env even before the first login request.
    check_database_ready()
    return {"status": "ready"}


@app.post("/api/login")
def login(body: LoginRequest, request: Request) -> dict[str, object]:
    AgentConfig.load()
    if not body.username or not body.password:
        raise HTTPException(status_code=422, detail="请输入用户名和密码")
    # Do not trust X-Forwarded-For from arbitrary clients. Behind a tunnel/proxy,
    # request.client.host may be the proxy's address rather than the visitor's.
    client_ip = request.client.host if request.client else "unknown"
    _login_limiter.check(client_ip, body.username)
    try:
        session_token, principal = create_login(body.username, body.password)
    except HTTPException as exc:
        if exc.status_code == 401:
            _login_limiter.failure(client_ip, body.username)
        raise
    _login_limiter.success(client_ip, body.username)
    try:
        initial_data = _bootstrap_for_principal(principal)
    except Exception:
        revoke_login(session_token)
        raise
    return {"session_token": session_token, "user_id": principal.user_id,
            "role": principal.role, "bootstrap": initial_data}


@app.post("/api/register", status_code=201)
def register(body: RegisterRequest) -> dict[str, str]:
    AgentConfig.load()
    register_user(body.username, body.password)
    return {"user_id": body.username.lower(), "status": "pending_approval"}


@app.post("/api/logout")
def logout(x_session_token: str | None = Header(default=None)) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    with _get_user_lock(principal.user_id):
        revoke_login(x_session_token)
        _release_harness(principal.user_id)
    return {"status": "ok"}


@app.get("/api/me")
def me(
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    return {"user_id": principal.user_id, "role": principal.role}


@app.get("/api/models")
def models(x_session_token: str | None = Header(default=None)) -> dict[str, list[dict]]:
    principal = resolve_login(x_session_token)
    return {"models": list_models(principal)}


@app.get("/api/engines")
def engines(x_session_token: str | None = Header(default=None)) -> dict[str, list[dict]]:
    resolve_login(x_session_token)
    return {"engines": [engine.public() for engine in list_dsh_engines()]}


@app.get("/api/workflows")
def workflow_list(x_session_token: str | None = Header(default=None)) -> dict[str, list[dict]]:
    principal = resolve_login(x_session_token)
    return {"workflows": list_workflows(principal)}


@app.post("/api/workflows", status_code=201)
def workflow_create(
    body: WorkflowDefinition, x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    workflow_id = save_workflow(principal, workflow_id=None, **body.model_dump())
    return {"workflow_id": workflow_id}


@app.put("/api/workflows/{workflow_id}")
def workflow_update(
    workflow_id: str, body: WorkflowDefinition,
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    get_workflow(principal, workflow_id)
    save_workflow(principal, workflow_id=workflow_id, **body.model_dump())
    return {"workflow_id": workflow_id}


@app.delete("/api/workflows/{workflow_id}")
def workflow_remove(
    workflow_id: str, x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    delete_workflow(principal, workflow_id)
    return {"status": "deleted"}


@app.post("/api/workflows/{workflow_id}/runs")
async def workflow_execute(
    workflow_id: str, body: WorkflowRunRequest,
    x_session_token: str | None = Header(default=None),
) -> dict:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    get_workflow(principal, workflow_id)

    def run() -> dict:
        with _get_user_lock(principal.user_id):
            resolve_login(x_session_token)
            current = get_workflow(principal, workflow_id)
            return execute_workflow(
                principal, current, input_text=body.input,
                provider=body.provider.strip().lower(), model=body.model.strip(),
                api_key=(body.api_key or "").strip() or None,
                providers_patch=_providers_patch.as_posix(),
                chat_patch=_chat_patch.as_posix(),
            )

    return await asyncio.to_thread(run)


@app.get("/api/workflows/{workflow_id}/runs")
def workflow_runs(
    workflow_id: str, x_session_token: str | None = Header(default=None),
) -> dict[str, list[dict]]:
    principal = resolve_login(x_session_token)
    return {"runs": list_workflow_runs(principal, workflow_id)}


@app.get("/api/workflow-runs/{run_id}")
def workflow_run_detail(
    run_id: str, x_session_token: str | None = Header(default=None),
) -> dict:
    principal = resolve_login(x_session_token)
    return get_workflow_run(principal, run_id)


@app.get("/api/bootstrap")
def bootstrap(x_session_token: str | None = Header(default=None)) -> dict[str, object]:
    """Return entry-page data in one HTTP round trip through the tunnel."""
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    return _bootstrap_for_principal(principal)


def _bootstrap_for_principal(principal: Principal) -> dict[str, object]:
    available = list_agents(principal)
    visible = available if principal.role == "admin" else [
        {"agent_id": item["agent_id"], "name": item["name"],
         "enabled": item["enabled"], "granted": item["granted"]}
        for item in available
    ]
    initial = next(
        (item for item in available if item["enabled"] and item["granted"]), None
    )
    return {
        "user": {"user_id": principal.user_id, "role": principal.role},
        "models": list_models(principal),
        "engines": [engine.public() for engine in list_dsh_engines()],
        "agents": visible,
        "initial_agent": _agent_details(initial, principal) if initial else None,
    }


def _agent_details(agent: dict, principal: Principal) -> dict[str, object]:
    return {"agent": {
        "agent_id": agent["agent_id"], "name": agent["name"],
        "instructions": agent["instructions"], "delegate_id": agent["delegate_id"],
    }, "capabilities": [
        {"capability_id": item["capability_id"],
         "display_id": item.get("display_id", item["capability_id"]),
         "scope": item.get("scope", "public"), "kind": item["kind"],
         "name": item["name"], "content": item["content"] if item["kind"] != "mcp" else ""}
        for item in effective_capabilities(principal, agent["agent_id"])
    ]}


@app.put("/api/admin/models/{provider}/{model_id}")
def update_model(provider: str, model_id: str, body: ModelSetting,
                 x_session_token: str | None = Header(default=None)) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    set_model(principal, provider, model_id, enabled=body.enabled,
              user_enabled=body.user_enabled)
    return {"provider": provider, "model_id": model_id}


@app.get("/api/agents")
def agents(x_session_token: str | None = Header(default=None)) -> dict[str, list[dict]]:
    principal = resolve_login(x_session_token)
    available = list_agents(principal)
    if principal.role != "admin":
        available = [
            {"agent_id": item["agent_id"], "name": item["name"],
             "enabled": item["enabled"], "granted": item["granted"]}
            for item in available
        ]
    return {"agents": available}


@app.get("/api/agents/{agent_id}/capabilities")
def visible_agent_capabilities(
    agent_id: str, x_session_token: str | None = Header(default=None),
) -> dict[str, object]:
    principal = resolve_login(x_session_token)
    agent = get_agent(principal, agent_id)
    return _agent_details(agent, principal)


@app.put("/api/admin/agents/{agent_id}")
def update_agent(agent_id: str, body: AgentSetting,
                 x_session_token: str | None = Header(default=None)) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    set_agent(principal, agent_id, name=body.name, instructions=body.instructions,
              delegate_id=body.delegate_id, enabled=body.enabled)
    return {"agent_id": agent_id}


@app.get("/api/admin/users/{user_id}/agents")
def user_agents(user_id: str, x_session_token: str | None = Header(default=None)) -> dict[str, list[str]]:
    principal = resolve_login(x_session_token)
    return {"agent_ids": list_grants(principal, user_id)}


@app.put("/api/admin/users/{user_id}/agents/{agent_id}")
def update_user_agent(user_id: str, agent_id: str, body: AgentGrant,
                      x_session_token: str | None = Header(default=None)) -> dict[str, bool]:
    principal = resolve_login(x_session_token)
    set_agent_grant(principal, user_id, agent_id, body.granted)
    return {"granted": body.granted}


@app.get("/api/admin/capabilities")
def admin_capabilities(x_session_token: str | None = Header(default=None)) -> dict[str, list[dict]]:
    principal = resolve_login(x_session_token)
    return {"capabilities": list_capabilities(principal)}


@app.put("/api/admin/capabilities/{capability_id}")
def update_capability(capability_id: str, body: CapabilitySetting,
                      x_session_token: str | None = Header(default=None)) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    set_capability(principal, capability_id, kind=body.kind, name=body.name,
                   content=body.content, endpoint=body.endpoint, enabled=body.enabled)
    return {"capability_id": capability_id}


@app.get("/api/admin/agents/{agent_id}/capabilities")
def agent_capabilities(agent_id: str,
                       x_session_token: str | None = Header(default=None)) -> dict[str, list[str]]:
    principal = resolve_login(x_session_token)
    return {"capability_ids": list_agent_capability_ids(principal, agent_id)}


@app.put("/api/admin/agents/{agent_id}/capabilities/{capability_id}")
def update_agent_capability(agent_id: str, capability_id: str, body: CapabilityAssignment,
                            x_session_token: str | None = Header(default=None)) -> dict[str, bool]:
    principal = resolve_login(x_session_token)
    set_agent_capability(principal, agent_id, capability_id, body.assigned)
    return {"assigned": body.assigned}


@app.get("/api/my/capabilities")
def my_capabilities(x_session_token: str | None = Header(default=None)) -> dict[str, list[dict]]:
    principal = resolve_login(x_session_token)
    return {"capabilities": list_own_capabilities(principal)}


@app.put("/api/my/capabilities/{capability_id}")
def update_my_capability(
    capability_id: str, body: CapabilitySetting,
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    with _get_user_lock(principal.user_id):
        set_own_capability(principal, capability_id, kind=body.kind, name=body.name,
                           content=body.content, endpoint=body.endpoint, enabled=body.enabled)
        _release_harness(principal.user_id)
    return {"capability_id": capability_id}


@app.delete("/api/my/capabilities/{capability_id}")
def remove_my_capability(
    capability_id: str, x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    principal = resolve_login(x_session_token)
    with _get_user_lock(principal.user_id):
        delete_own_capability(principal, capability_id)
        _release_harness(principal.user_id)
    return {"status": "deleted"}


@app.get("/api/my/agents/{agent_id}/capabilities")
def my_agent_capabilities(
    agent_id: str, x_session_token: str | None = Header(default=None),
) -> dict[str, list[str]]:
    principal = resolve_login(x_session_token)
    return {"capability_ids": list_own_assignments(principal, agent_id)}


@app.put("/api/my/agents/{agent_id}/capabilities/{capability_id}")
def update_my_agent_capability(
    agent_id: str, capability_id: str, body: CapabilityAssignment,
    x_session_token: str | None = Header(default=None),
) -> dict[str, bool]:
    principal = resolve_login(x_session_token)
    with _get_user_lock(principal.user_id):
        set_own_assignment(principal, agent_id, capability_id, body.assigned)
        _release_harness(principal.user_id)
    return {"assigned": body.assigned}


@app.get("/api/admin/user-mcps")
def admin_user_mcps(x_session_token: str | None = Header(default=None)) -> dict[str, list[dict]]:
    principal = resolve_login(x_session_token)
    return {"mcps": list_user_mcps(principal)}


@app.put("/api/admin/users/{user_id}/mcps/{capability_id}/approval")
def update_user_mcp_approval(
    user_id: str, capability_id: str, body: McpApproval,
    x_session_token: str | None = Header(default=None),
) -> dict[str, bool]:
    principal = resolve_login(x_session_token)
    user_id = user_id.lower()
    with _get_user_lock(user_id):
        set_user_mcp_approval(principal, user_id, capability_id, body.approved)
        _release_harness(user_id)
    return {"approved": body.approved}


@app.get("/api/admin/users")
def admin_users(
    x_session_token: str | None = Header(default=None),
) -> dict[str, list[dict[str, str | int | bool]]]:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    return {"users": list_users(principal)}


@app.patch("/api/admin/users/{user_id}")
def update_user(
    user_id: str,
    body: UserStatusRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, str | bool]:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    with _get_user_lock(user_id.lower()):
        set_user_enabled(principal, user_id, body.enabled)
        if not body.enabled:
            _release_harness(user_id.lower())
    return {"user_id": user_id, "enabled": body.enabled}


@app.delete("/api/admin/users/{user_id}")
def remove_user(
    user_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    with _get_user_lock(user_id.lower()):
        delete_user(principal, user_id)
        _release_harness(user_id.lower())
    return {"user_id": user_id, "status": "deleted"}


@app.put("/api/admin/users/{user_id}/password")
def update_user_password(
    user_id: str,
    body: ResetPasswordRequest,
    x_session_token: str | None = Header(default=None),
) -> dict[str, str]:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    with _get_user_lock(user_id.lower()):
        reset_user_password(principal, user_id, body.password)
        _release_harness(user_id.lower())
    return {"user_id": user_id, "status": "password_changed"}


@app.get("/api/chats")
def chats(x_session_token: str | None = Header(default=None)) -> dict[str, list[dict]]:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    return {"chats": list_chats(principal)}


@app.get("/api/chat/{session_id}/messages")
def chat_messages(
    session_id: str, x_session_token: str | None = Header(default=None),
) -> dict[str, list[dict]]:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    if not _session_id_pattern.fullmatch(session_id):
        raise HTTPException(status_code=422, detail="会话 ID 无效")
    return {"messages": list_messages(session_id, principal)}


@app.delete("/api/chat/{session_id}")
def remove_chat(session_id: str, x_session_token: str | None = Header(default=None)) -> dict[str, str]:
    AgentConfig.load()
    principal = resolve_login(x_session_token)
    if not _session_id_pattern.fullmatch(session_id):
        raise HTTPException(status_code=422, detail="会话 ID 无效")
    with _get_user_lock(principal.user_id):
        delete_chat(session_id, principal)
        with _harnesses_guard:
            _runtime_sessions.pop((principal.user_id, session_id), None)
    return {"status": "deleted"}


def _save_chat_message(session_id: str, user_id: str, role: str, content: str, **metadata: str) -> None:
    try:
        save_message(session_id, user_id, role, content, **metadata)
    except Exception:
        # A history write must never discard a model reply the user already paid for.
        logger.exception("Could not persist chat message for user %s", user_id)


def _resume_context(messages: list[dict]) -> str:
    """Replay recent completed text turns when a DSH process cannot resume its log."""
    pairs: list[dict[str, str]] = []
    pending_user: str | None = None
    for item in messages:
        if item["role"] == "user":
            pending_user = str(item["content"])
        elif item["role"] == "assistant" and pending_user is not None:
            pairs.append({"user": pending_user, "assistant": str(item["content"])})
            pending_user = None
    selected: list[dict[str, str]] = []
    size = 0
    for pair in reversed(pairs[-20:]):
        bounded = {role: content[-4000:] for role, content in pair.items()}
        length = sum(len(content) for content in bounded.values())
        if size + length > 24000:
            break
        selected.append(bounded)
        size += length
    if not selected:
        return ""
    selected.reverse()
    return (
        "以下是这个会话之前已完成的文字对话，仅用于延续上下文；"
        "工具执行状态未恢复。请根据本轮用户消息继续回答：\n"
        + json.dumps(selected, ensure_ascii=False)
    )


def _agent_input(
    message: str, instructions: str, delegate_answer: str = "", resume_context: str = "",
) -> str:
    if not instructions and not delegate_answer and not resume_context:
        return message
    sections = []
    if instructions:
        sections.append("管理员设置的 Agent 指令：\n" + instructions)
    if delegate_answer:
        sections.append("协作 Agent 的分析（供参考，请自行核对）：\n" + delegate_answer[:8000])
    if resume_context:
        sections.append(resume_context)
    sections.append("用户消息：\n" + message)
    return "\n\n".join(sections)


def _run_delegate(config: AgentConfig, principal: Principal, agent: dict, *, message: str, provider: str,
                  model: str, api_key: str | None, deadline: float) -> str:
    delegated = replace(
        config,
        workspace=config.workspace / "agents" / agent["agent_id"],
        harness_home=config.harness_home / "agents" / agent["agent_id"],
    )
    delegated, prompt, _ = prepare_capabilities(delegated, agent["agent_id"], principal)
    options = {"provider": provider, "model": model, "isolate_other_keys": True}
    if api_key:
        options["api_key"] = api_key
    child = create_harness(delegated, **options)
    try:
        _call_harness_with_deadline(child, child.start, deadline)
        result = _call_harness_with_deadline(
            child,
            lambda: child.run(_agent_input(message, "\n\n".join(
                part for part in (agent["instructions"], prompt) if part)),
                              session_id=uuid4().hex),
            deadline,
        )
        answer = (result.final_response or "").strip()
        if result.finish_reason != "completed" or not answer:
            raise HTTPException(502, "协作 Agent 未完成任务")
        return answer
    finally:
        child.close()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    x_session_token: str | None = Header(default=None),
) -> ChatResponse:
    # Admit before allocating a long-lived worker thread. shield keeps the slot
    # occupied if the browser disconnects while its synchronous SDK call runs.
    principal = await asyncio.to_thread(resolve_login, x_session_token)
    _admit_chat(principal.user_id)
    try:
        work = asyncio.create_task(asyncio.to_thread(_chat_sync, body, x_session_token, principal))
    except BaseException:
        _release_chat_slot(principal.user_id)
        raise

    def finished(task: asyncio.Task) -> None:
        _release_chat_slot(principal.user_id)
        if not task.cancelled():
            task.exception()  # Observe errors if the HTTP client disconnected.

    try:
        return await asyncio.shield(work)
    finally:
        if work.done():
            finished(work)
        else:
            work.add_done_callback(finished)


def _chat_sync(body: ChatRequest, x_session_token: str | None, principal) -> ChatResponse:
    config = AgentConfig.load()  # Also loads local .env without overriding host secrets.
    engine = get_engine(body.engine_id)
    user_api_key = (body.api_key or "").strip()
    provider = body.provider.strip().lower()
    model = (body.model or "").strip() or (config.model if provider == "deepseek-official" else "")
    if not _model_id_pattern.fullmatch(model):
        raise HTTPException(status_code=422, detail="请填写有效的模型 ID")
    require_model(principal, provider, model)
    agent = get_agent(principal, body.agent_id)
    if not user_api_key and (principal.role == "user" or provider != "deepseek-official"):
        raise HTTPException(status_code=422, detail="请填写所选模型厂家的 API Key")
    if len(user_api_key) > 512:
        raise HTTPException(status_code=422, detail="API Key 长度无效")
    if principal.role == "admin" and provider == "deepseek-official" and not user_api_key and not config.has_api_key:
        raise HTTPException(status_code=503, detail="服务尚未配置 DeepSeek API Key")
    config = configure_web_engine(config, principal.user_id, engine)
    config = replace(config, patches=(_providers_patch.as_posix(), _chat_patch.as_posix()))

    session_id = body.session_id or uuid4().hex
    with _get_user_lock(principal.user_id):
        # Recheck after waiting: an administrator may have disabled or reset the account.
        resolve_login(x_session_token)
        require_model(principal, provider, model)
        agent = get_agent(principal, body.agent_id)
        check_or_create_session(session_id, principal, new=body.session_id is None)
        bind_session_agent(session_id, body.agent_id, new=body.session_id is None)
        bind_session_engine(session_id, engine.engine_id, new=body.session_id is None)
        runtime_key = (principal.user_id, session_id)
        with _harnesses_guard:
            runtime_session_id = _runtime_sessions.get(runtime_key)
        resume_context = ""
        if runtime_session_id is None and body.session_id is not None:
            try:
                resume_context = _resume_context(list_messages(session_id, principal))
            except HTTPException as exc:
                if exc.status_code == 503:
                    raise HTTPException(
                        status_code=409, detail="服务端历史尚未启用，无法续接；请点击“新会话”"
                    ) from None
                raise
        _save_chat_message(
            session_id, principal.user_id, "user", body.message, provider=provider, model=model,
        )
        try:
            # One user's Harness is serialized; other users can run concurrently.
            deadline = monotonic() + _chat_timeout_seconds()
            config, capability_prompt, capabilities_hash = prepare_capabilities(
                config, body.agent_id, principal
            )
            harness = _get_harness(
                config, principal.user_id,
                api_key=user_api_key or None, provider=provider, model=model,
                agent_id=body.agent_id, capabilities_hash=capabilities_hash,
                new_session=body.session_id is None, deadline=deadline,
            )
            delegate_answer = ""
            if agent["delegate_id"]:
                delegate = get_agent(Principal(principal.user_id, "admin"), agent["delegate_id"])
                delegate_answer = _run_delegate(
                    config, principal, delegate, message=body.message, provider=provider,
                    model=model, api_key=user_api_key or None, deadline=deadline,
                )
            if runtime_session_id is None:
                runtime_session_id = session_id if body.session_id is None else uuid4().hex
                with _harnesses_guard:
                    _runtime_sessions[runtime_key] = runtime_session_id
            result = _call_harness_with_deadline(
                harness,
                lambda: harness.run(
                    _agent_input(body.message, "\n\n".join(
                        part for part in (agent["instructions"], capability_prompt) if part),
                                 delegate_answer, resume_context),
                    session_id=runtime_session_id,
                ),
                deadline,
            )
        except HTTPException as exc:
            if exc.status_code == 504:
                _release_harness(principal.user_id)
            raise
        except Exception as exc:
            if principal.role == "user":
                logger.error("Harness request failed for user %s (%s)", principal.user_id, type(exc).__name__)
            else:
                logger.exception("Harness request failed")
            try:
                _release_harness(principal.user_id)
            except Exception:
                logger.exception("Failed to close Harness after request error")
            if isinstance(exc, JsonRpcError) and "already exists" in exc.message.lower():
                raise HTTPException(
                    status_code=409, detail="该会话无法在服务重启后续接，请点击“新会话”再发送"
                ) from None
            if isinstance(exc, JsonRpcError) and "has no configured model" in exc.message.lower():
                raise HTTPException(
                    status_code=422, detail="该厂家没有配置这个模型 ID，请检查模型名称"
                ) from None
            raise HTTPException(status_code=502, detail="Agent 调用失败，请检查服务日志") from None

        if result.finish_reason != "completed":
            logger.error("Harness turn ended with reason: %s", result.finish_reason)
            detail = (
                "模型调用失败，请检查所选厂家、模型 ID、API Key、账户余额和网络连接"
                if user_api_key else "Agent 未完成本轮请求，请检查模型连接和服务日志"
            )
            raise HTTPException(status_code=502, detail=detail)
        answer = (result.final_response or "").strip()
        if not answer:
            raise HTTPException(status_code=502, detail="Agent 没有返回文字")
        _save_chat_message(session_id, principal.user_id, "assistant", answer)
        trace = summarize_run_events(getattr(result, "events", []))
        return ChatResponse(answer=answer, session_id=session_id,
                            engine_id=engine.engine_id, **trace)
