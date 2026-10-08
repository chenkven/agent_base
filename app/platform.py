"""MySQL backed model, Agent, and per-user access configuration.

This module owns configuration data. The web layer owns HTTP and the Harness
layer owns execution; a model or Agent is checked here before either runs.
"""

from contextlib import closing
import re
from urllib.parse import urlsplit

from fastapi import HTTPException
import mysql.connector

from app.permissions import Principal, _connect, require_admin


IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
SKILL_IDENTIFIER = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
PROVIDERS = {
    "deepseek-official", "qwen-bailian", "openai", "anthropic", "moonshotai", "zai",
}


def _database_error(exc: mysql.connector.Error) -> None:
    if exc.errno == 1146:
        raise HTTPException(503, "平台配置表尚未安装，请运行 mysql/migrate_platform.sql") from None
    raise exc


def list_models(principal: Principal) -> list[dict]:
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT provider, model_id, enabled, user_enabled FROM model_catalog "
                "ORDER BY provider, model_id"
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"provider": provider, "model_id": model, "enabled": bool(enabled),
         "user_enabled": bool(user_enabled)}
        for provider, model, enabled, user_enabled in rows
        if principal.role == "admin" or (enabled and user_enabled)
    ]


def set_model(principal: Principal, provider: str, model: str, *, enabled: bool,
              user_enabled: bool) -> None:
    require_admin(principal)
    if provider not in PROVIDERS or not MODEL_ID.fullmatch(model):
        raise HTTPException(422, "模型厂家或 ID 无效")
    try:
        with closing(_connect()) as db:
            with db:
                db.execute(
                    "INSERT INTO model_catalog (provider, model_id, enabled, user_enabled) "
                    "VALUES (?, ?, ?, ?) ON DUPLICATE KEY UPDATE enabled = VALUES(enabled), "
                    "user_enabled = VALUES(user_enabled)",
                    (provider, model, int(enabled), int(user_enabled)),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)


def require_model(principal: Principal, provider: str, model: str) -> None:
    if provider not in PROVIDERS or not MODEL_ID.fullmatch(model):
        raise HTTPException(422, "模型厂家或 ID 无效")
    try:
        with closing(_connect()) as db:
            row = db.execute(
                "SELECT enabled, user_enabled FROM model_catalog "
                "WHERE provider = ? AND model_id = ?", (provider, model),
            ).fetchone()
    except mysql.connector.Error as exc:
        _database_error(exc)
    if row is None or not row[0] or (principal.role != "admin" and not row[1]):
        raise HTTPException(403, "当前账号无权使用该模型")


def list_agents(principal: Principal) -> list[dict]:
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT a.agent_id, a.name, a.instructions, a.delegate_id, a.enabled, "
                "g.user_id FROM agent_profiles a LEFT JOIN user_agent_grants g "
                "ON g.agent_id = a.agent_id AND g.user_id = ? ORDER BY a.agent_id",
                (principal.user_id,),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"agent_id": agent_id, "name": name, "instructions": instructions,
         "delegate_id": delegate_id, "enabled": bool(enabled),
         "granted": bool(granted) or agent_id == "default" or principal.role == "admin"}
        for agent_id, name, instructions, delegate_id, enabled, granted in rows
        if principal.role == "admin" or (enabled and (granted or agent_id == "default"))
    ]


def get_agent(principal: Principal, agent_id: str) -> dict:
    if not IDENTIFIER.fullmatch(agent_id):
        raise HTTPException(422, "Agent ID 无效")
    agents = list_agents(principal)
    agent = next((item for item in agents if item["agent_id"] == agent_id), None)
    if agent is None or not agent["enabled"] or not agent["granted"]:
        raise HTTPException(403, "当前账号无权使用该 Agent")
    return agent


def set_agent(principal: Principal, agent_id: str, *, name: str, instructions: str,
              delegate_id: str | None, enabled: bool) -> None:
    require_admin(principal)
    if not IDENTIFIER.fullmatch(agent_id) or not 1 <= len(name.strip()) <= 80:
        raise HTTPException(422, "Agent ID 或名称无效")
    if len(instructions) > 8000:
        raise HTTPException(422, "Agent 指令过长")
    if delegate_id is not None and (not IDENTIFIER.fullmatch(delegate_id) or delegate_id == agent_id):
        raise HTTPException(422, "协作 Agent ID 无效")
    if agent_id == "default" and not enabled:
        raise HTTPException(422, "默认 Agent 不能停用")
    try:
        with closing(_connect()) as db:
            with db:
                if delegate_id:
                    row = db.execute(
                        "SELECT enabled, delegate_id FROM agent_profiles WHERE agent_id = ?",
                        (delegate_id,),
                    ).fetchone()
                    if row is None or not row[0] or row[1]:
                        raise HTTPException(422, "协作 Agent 必须存在、启用，且不能再委派")
                    incoming = db.execute(
                        "SELECT agent_id FROM agent_profiles WHERE delegate_id = ? LIMIT 1",
                        (agent_id,),
                    ).fetchone()
                    if incoming:
                        raise HTTPException(422, "已被其他 Agent 使用的协作 Agent 不能再委派")
                if not enabled:
                    incoming = db.execute(
                        "SELECT agent_id FROM agent_profiles WHERE delegate_id = ? LIMIT 1",
                        (agent_id,),
                    ).fetchone()
                    if incoming:
                        raise HTTPException(422, "该 Agent 正被其他 Agent 使用，不能停用")
                db.execute(
                    "INSERT INTO agent_profiles (agent_id, name, instructions, delegate_id, enabled) "
                    "VALUES (?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE "
                    "name = VALUES(name), instructions = VALUES(instructions), "
                    "delegate_id = VALUES(delegate_id), enabled = VALUES(enabled)",
                    (agent_id, name.strip(), instructions.strip(), delegate_id, int(enabled)),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)


def set_agent_grant(principal: Principal, user_id: str, agent_id: str,
                    granted: bool) -> None:
    require_admin(principal)
    if not IDENTIFIER.fullmatch(user_id) or not IDENTIFIER.fullmatch(agent_id):
        raise HTTPException(422, "用户或 Agent ID 无效")
    if agent_id == "default":
        raise HTTPException(422, "默认 Agent 对所有已启用账号开放")
    try:
        with closing(_connect()) as db:
            with db:
                account = db.execute(
                    "SELECT role, disabled FROM accounts WHERE user_id = ?", (user_id,)
                ).fetchone()
                agent = db.execute(
                    "SELECT agent_id FROM agent_profiles WHERE agent_id = ?", (agent_id,)
                ).fetchone()
                if account is None or account[0] != "user" or account[1] == 2 or agent is None:
                    raise HTTPException(404, "用户或 Agent 不存在")
                if granted:
                    db.execute(
                        "INSERT IGNORE INTO user_agent_grants (user_id, agent_id) VALUES (?, ?)",
                        (user_id, agent_id),
                    )
                else:
                    db.execute(
                        "DELETE FROM user_agent_grants WHERE user_id = ? AND agent_id = ?",
                        (user_id, agent_id),
                    )
    except mysql.connector.Error as exc:
        _database_error(exc)


def list_grants(principal: Principal, user_id: str) -> list[str]:
    require_admin(principal)
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT agent_id FROM user_agent_grants WHERE user_id = ? ORDER BY agent_id",
                (user_id,),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [row[0] for row in rows]


def bind_session_agent(session_id: str, agent_id: str, *, new: bool) -> None:
    """Keep an existing chat attached to its original Agent."""
    try:
        with closing(_connect()) as db:
            with db:
                if new:
                    db.execute(
                        "INSERT INTO session_agents (session_id, agent_id) VALUES (?, ?)",
                        (session_id, agent_id),
                    )
                else:
                    row = db.execute(
                        "SELECT agent_id FROM session_agents WHERE session_id = ?", (session_id,)
                    ).fetchone()
                    original = row[0] if row else "default"  # Chats created before migration.
                    if original != agent_id:
                        raise HTTPException(409, "该会话属于其他 Agent，请新建会话")
    except mysql.connector.Error as exc:
        _database_error(exc)


def list_capabilities(principal: Principal) -> list[dict]:
    require_admin(principal)
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT capability_id, kind, name, content, endpoint, enabled "
                "FROM capability_catalog ORDER BY capability_id"
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"capability_id": cap_id, "kind": kind, "name": name,
         "content": content or "", "endpoint": endpoint or "", "enabled": bool(enabled)}
        for cap_id, kind, name, content, endpoint, enabled in rows
    ]


def set_capability(principal: Principal, capability_id: str, *, kind: str,
                   name: str, content: str, endpoint: str, enabled: bool) -> None:
    require_admin(principal)
    if not IDENTIFIER.fullmatch(capability_id) or kind not in {"prompt", "skill", "mcp"}:
        raise HTTPException(422, "能力 ID 或类型无效")
    if kind == "skill" and not SKILL_IDENTIFIER.fullmatch(capability_id):
        raise HTTPException(422, "Skill ID 只能使用小写字母、数字和连接符（如 review-skill）")
    if not 1 <= len(name.strip()) <= 80 or "\n" in name or "\r" in name:
        raise HTTPException(422, "能力名称无效")
    if len(content) > 16000:
        raise HTTPException(422, "能力内容过长")
    if kind in {"prompt", "skill"} and not content.strip():
        raise HTTPException(422, "请填写 Prompt 或 Skill 内容")
    if kind == "mcp":
        try:
            parsed = urlsplit(endpoint)
        except ValueError:
            raise HTTPException(422, "MCP 地址无效") from None
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise HTTPException(422, "MCP 地址必须是有效的 HTTP(S) URL，且不能包含账号密码")
        if len(endpoint) > 2048:
            raise HTTPException(422, "MCP 地址过长")
    else:
        endpoint = ""
    try:
        with closing(_connect()) as db:
            with db:
                existing = db.execute(
                    "SELECT kind FROM capability_catalog WHERE capability_id = ?",
                    (capability_id,),
                ).fetchone()
                if existing and existing[0] != kind:
                    raise HTTPException(409, "已有能力不能改变类型，请使用新的 ID")
                db.execute(
                    "INSERT INTO capability_catalog "
                    "(capability_id, kind, name, content, endpoint, enabled) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE "
                    "name = VALUES(name), content = VALUES(content), "
                    "endpoint = VALUES(endpoint), enabled = VALUES(enabled)",
                    (capability_id, kind, name.strip(), content.strip(), endpoint, int(enabled)),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)


def set_agent_capability(principal: Principal, agent_id: str, capability_id: str,
                         assigned: bool) -> None:
    require_admin(principal)
    if not IDENTIFIER.fullmatch(agent_id) or not IDENTIFIER.fullmatch(capability_id):
        raise HTTPException(422, "Agent 或能力 ID 无效")
    try:
        with closing(_connect()) as db:
            with db:
                agent = db.execute(
                    "SELECT agent_id FROM agent_profiles WHERE agent_id = ?", (agent_id,)
                ).fetchone()
                capability = db.execute(
                    "SELECT kind FROM capability_catalog WHERE capability_id = ?",
                    (capability_id,),
                ).fetchone()
                if not agent or not capability:
                    raise HTTPException(404, "Agent 或能力不存在")
                if assigned and agent_id == "default" and capability[0] == "mcp":
                    raise HTTPException(422, "MCP 不能分配给所有用户可用的默认 Agent")
                if assigned:
                    db.execute(
                        "INSERT IGNORE INTO agent_capabilities (agent_id, capability_id) "
                        "VALUES (?, ?)", (agent_id, capability_id),
                    )
                else:
                    db.execute(
                        "DELETE FROM agent_capabilities WHERE agent_id = ? AND capability_id = ?",
                        (agent_id, capability_id),
                    )
    except mysql.connector.Error as exc:
        _database_error(exc)


def capabilities_for_agent(agent_id: str) -> list[dict]:
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT c.capability_id, c.kind, c.name, c.content, c.endpoint "
                "FROM agent_capabilities ac JOIN capability_catalog c "
                "ON c.capability_id = ac.capability_id "
                "WHERE ac.agent_id = ? AND c.enabled = 1 ORDER BY c.capability_id",
                (agent_id,),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"capability_id": cap_id, "kind": kind, "name": name,
         "content": content or "", "endpoint": endpoint or ""}
        for cap_id, kind, name, content, endpoint in rows
    ]


def list_agent_capability_ids(principal: Principal, agent_id: str) -> list[str]:
    require_admin(principal)
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT capability_id FROM agent_capabilities WHERE agent_id = ? ORDER BY capability_id",
                (agent_id,),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [row[0] for row in rows]
