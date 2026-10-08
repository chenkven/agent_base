"""Capabilities owned by one account, separate from administrator catalog entries."""

from contextlib import closing
from hashlib import sha256
from urllib.parse import urlsplit

from fastapi import HTTPException
import mysql.connector

from app.permissions import Principal, _connect
from app.platform import (
    IDENTIFIER, SKILL_IDENTIFIER, _database_error, capabilities_for_agent, get_agent,
)


def _validate(capability_id: str, kind: str, name: str, content: str, endpoint: str) -> str:
    if not IDENTIFIER.fullmatch(capability_id) or kind not in {"prompt", "skill", "mcp"}:
        raise HTTPException(422, "能力 ID 或类型无效")
    if kind == "skill" and not SKILL_IDENTIFIER.fullmatch(capability_id):
        raise HTTPException(422, "Skill ID 只能使用小写字母、数字和连接符")
    if not 1 <= len(name.strip()) <= 80 or "\n" in name or "\r" in name:
        raise HTTPException(422, "能力名称无效")
    if len(content) > 16000:
        raise HTTPException(422, "能力内容过长")
    if kind in {"prompt", "skill"}:
        if not content.strip():
            raise HTTPException(422, "请填写 Prompt 或 Skill 内容")
        return ""
    try:
        parsed = urlsplit(endpoint)
    except ValueError:
        raise HTTPException(422, "MCP 地址无效") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.netloc
            or parsed.username or parsed.password or len(endpoint) > 2048):
        raise HTTPException(422, "MCP 地址必须是有效的 HTTP(S) URL，且不能包含账号密码")
    return endpoint


def list_own_capabilities(principal: Principal) -> list[dict]:
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT capability_id, kind, name, content, endpoint, enabled, approved "
                "FROM user_capabilities WHERE user_id = ? ORDER BY capability_id",
                (principal.user_id,),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"capability_id": cap_id, "kind": kind, "name": name,
         "content": content or "", "endpoint": endpoint or "",
         "enabled": bool(enabled), "approved": bool(approved)}
        for cap_id, kind, name, content, endpoint, enabled, approved in rows
    ]


def set_own_capability(
    principal: Principal, capability_id: str, *, kind: str, name: str,
    content: str, endpoint: str, enabled: bool,
) -> None:
    endpoint = _validate(capability_id, kind, name, content, endpoint)
    try:
        with closing(_connect()) as db:
            with db:
                existing = db.execute(
                    "SELECT kind, endpoint, approved FROM user_capabilities "
                    "WHERE user_id = ? AND capability_id = ? FOR UPDATE",
                    (principal.user_id, capability_id),
                ).fetchone()
                if existing and existing[0] != kind:
                    raise HTTPException(409, "已有能力不能改变类型，请使用新的 ID")
                approved = kind != "mcp" or bool(existing and existing[1] == endpoint and existing[2])
                db.execute(
                    "INSERT INTO user_capabilities "
                    "(user_id, capability_id, kind, name, content, endpoint, enabled, approved) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE "
                    "name = VALUES(name), content = VALUES(content), endpoint = VALUES(endpoint), "
                    "enabled = VALUES(enabled), approved = VALUES(approved)",
                    (principal.user_id, capability_id, kind, name.strip(),
                     content.strip() if kind != "mcp" else "", endpoint,
                     int(enabled), int(approved)),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)


def delete_own_capability(principal: Principal, capability_id: str) -> None:
    try:
        with closing(_connect()) as db:
            with db:
                deleted = db.execute(
                    "DELETE FROM user_capabilities WHERE user_id = ? AND capability_id = ?",
                    (principal.user_id, capability_id),
                )
                if not deleted.rowcount:
                    raise HTTPException(404, "能力不存在")
    except mysql.connector.Error as exc:
        _database_error(exc)


def list_own_assignments(principal: Principal, agent_id: str) -> list[str]:
    get_agent(principal, agent_id)
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT capability_id FROM user_agent_capabilities "
                "WHERE user_id = ? AND agent_id = ? ORDER BY capability_id",
                (principal.user_id, agent_id),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [row[0] for row in rows]


def set_own_assignment(
    principal: Principal, agent_id: str, capability_id: str, assigned: bool,
) -> None:
    get_agent(principal, agent_id)
    if not IDENTIFIER.fullmatch(capability_id):
        raise HTTPException(422, "能力 ID 无效")
    try:
        with closing(_connect()) as db:
            with db:
                owned = db.execute(
                    "SELECT 1 FROM user_capabilities WHERE user_id = ? AND capability_id = ?",
                    (principal.user_id, capability_id),
                ).fetchone()
                if not owned:
                    raise HTTPException(404, "能力不存在")
                if assigned:
                    db.execute(
                        "INSERT IGNORE INTO user_agent_capabilities "
                        "(user_id, agent_id, capability_id) VALUES (?, ?, ?)",
                        (principal.user_id, agent_id, capability_id),
                    )
                else:
                    db.execute(
                        "DELETE FROM user_agent_capabilities "
                        "WHERE user_id = ? AND agent_id = ? AND capability_id = ?",
                        (principal.user_id, agent_id, capability_id),
                    )
    except mysql.connector.Error as exc:
        _database_error(exc)


def own_capabilities_for_agent(principal: Principal, agent_id: str) -> list[dict]:
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT c.capability_id, c.kind, c.name, c.content, c.endpoint "
                "FROM user_agent_capabilities a JOIN user_capabilities c "
                "ON c.user_id = a.user_id AND c.capability_id = a.capability_id "
                "WHERE a.user_id = ? AND a.agent_id = ? AND c.enabled = 1 "
                "AND (c.kind <> 'mcp' OR c.approved = 1) ORDER BY c.capability_id",
                (principal.user_id, agent_id),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"capability_id": "user-" + sha256(
            f"{principal.user_id}\0{cap_id}".encode()).hexdigest()[:16],
         "display_id": cap_id, "scope": "personal", "kind": kind, "name": name,
         "content": content or "", "endpoint": endpoint or ""}
        for cap_id, kind, name, content, endpoint in rows
    ]


def effective_capabilities(principal: Principal, agent_id: str) -> list[dict]:
    return capabilities_for_agent(agent_id) + own_capabilities_for_agent(principal, agent_id)


def list_user_mcps(principal: Principal) -> list[dict]:
    from app.permissions import require_admin
    require_admin(principal)
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT user_id, capability_id, name, endpoint, enabled, approved "
                "FROM user_capabilities WHERE kind = 'mcp' ORDER BY user_id, capability_id"
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"user_id": user_id, "capability_id": cap_id, "name": name,
         "endpoint": endpoint, "enabled": bool(enabled), "approved": bool(approved)}
        for user_id, cap_id, name, endpoint, enabled, approved in rows
    ]


def set_user_mcp_approval(
    principal: Principal, user_id: str, capability_id: str, approved: bool,
) -> None:
    from app.permissions import require_admin
    require_admin(principal)
    if not IDENTIFIER.fullmatch(user_id) or not IDENTIFIER.fullmatch(capability_id):
        raise HTTPException(422, "用户或能力 ID 无效")
    try:
        with closing(_connect()) as db:
            with db:
                existing = db.execute(
                    "SELECT 1 FROM user_capabilities WHERE user_id = ? "
                    "AND capability_id = ? AND kind = 'mcp' FOR UPDATE",
                    (user_id, capability_id),
                ).fetchone()
                if not existing:
                    raise HTTPException(404, "用户 MCP 不存在")
                db.execute(
                    "UPDATE user_capabilities SET approved = ? WHERE user_id = ? "
                    "AND capability_id = ? AND kind = 'mcp'",
                    (int(approved), user_id, capability_id),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)
