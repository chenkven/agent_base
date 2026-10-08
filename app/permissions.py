"""MySQL 账户、登录会话以及为网页服务提供的用户聊天权限."""

from contextlib import closing
from dataclasses import dataclass
from hashlib import scrypt, sha256
from hmac import compare_digest
import os
import re
import secrets
import time

from fastapi import HTTPException
import mysql.connector

_USER_ID = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
LOGIN_SECONDS = 8 * 60 * 60
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 5


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = scrypt(
        password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
        p=_SCRYPT_P, maxmem=64 * 1024 * 1024, dklen=32,
    )
    return f"scrypt:{_SCRYPT_N}:{_SCRYPT_R}:{_SCRYPT_P}:{salt.hex()}:{derived.hex()}"


def _check_password(password: str, stored: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = stored.split(":")
        if algorithm != "scrypt":
            return False
        derived = scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r),
            p=int(p), maxmem=64 * 1024 * 1024, dklen=32,
        )
        return compare_digest(derived, bytes.fromhex(expected))
    except (ValueError, OverflowError):
        return False


class DbConnection:
    """Small adapter so each request owns one MySQL transaction and its cursors."""

    def __init__(self, raw):
        self.raw = raw
        self.cursors = []

    def execute(self, sql: str, params: tuple = ()):
        cursor = self.raw.cursor(buffered=True)
        cursor.execute(sql.replace("?", "%s"), params)
        self.cursors.append(cursor)
        return cursor

    def __enter__(self):
        return self

    def __exit__(self, error_type, _error, _traceback):
        if error_type:
            self.raw.rollback()
        else:
            self.raw.commit()

    def close(self):
        for cursor in self.cursors:
            cursor.close()
        self.raw.close()


def _connect() -> DbConnection:
    user = os.getenv("MYSQL_USER", "").strip()
    password = os.getenv("MYSQL_PASSWORD", "")
    if not user or not password:
        raise HTTPException(status_code=503, detail="服务尚未配置 MySQL 账号")
    try:
        raw = mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            database=os.getenv("MYSQL_DATABASE", "agent_base"),
            user=user, password=password, connection_timeout=5,
        )
    except (mysql.connector.Error, ValueError):
        raise HTTPException(status_code=503, detail="MySQL 连接失败，请检查数据库配置") from None
    connection = DbConnection(raw)
    try:
        if connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0:
            admin_password = os.getenv("SERVICE_ACCESS_TOKEN", "").strip()
            if not admin_password:
                raise HTTPException(status_code=503, detail="请先配置管理员初始密码")
            with connection:
                connection.execute(
                    "INSERT IGNORE INTO accounts (user_id, role, password_hash, disabled) "
                    "VALUES (?, ?, ?, ?)",
                    ("admin", "admin", _password_hash(admin_password), 0),
                )
        return connection
    except mysql.connector.Error:
        connection.close()
        raise HTTPException(status_code=503, detail="MySQL 表未就绪，请先运行安装脚本") from None
    except Exception:
        connection.close()
        raise


def check_database_ready() -> None:
    """Probe the database without creating an account or modifying data."""
    user = os.getenv("MYSQL_USER", "").strip()
    password = os.getenv("MYSQL_PASSWORD", "")
    if not user or not password:
        raise HTTPException(status_code=503, detail="服务尚未配置 MySQL 账号")
    try:
        with closing(mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            database=os.getenv("MYSQL_DATABASE", "agent_base"),
            user=user, password=password, connection_timeout=5,
        )) as connection:
            with closing(connection.cursor()) as cursor:
                for table in (
                    "accounts", "login_sessions", "sessions", "model_catalog",
                    "agent_profiles", "user_agent_grants", "session_agents",
                    "capability_catalog", "agent_capabilities",
                    "user_capabilities", "user_agent_capabilities",
                    "session_engines", "workflows", "workflow_runs",
                    "workflow_step_runs",
                ):
                    cursor.execute(f"SELECT 1 FROM {table} LIMIT 1")
                    cursor.fetchall()
    except (mysql.connector.Error, ValueError):
        raise HTTPException(status_code=503, detail="MySQL 尚未就绪") from None


def _account(connection: DbConnection, user_id: str):
    return connection.execute(
        "SELECT role, password_hash, disabled FROM accounts WHERE user_id = ?", (user_id.lower(),)
    ).fetchone()


def authenticate(user_id: str, password: str) -> Principal:
    user_id = user_id.lower()
    with closing(_connect()) as connection:
        row = _account(connection, user_id)
    if row is None or not _check_password(password, row[1]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if row[2]:
        raise HTTPException(status_code=403, detail="账号已停用")
    return Principal(user_id, row[0])


def require_admin(principal: Principal) -> None:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")


def create_login(user_id: str, password: str) -> tuple[str, Principal]:
    principal = authenticate(user_id, password)
    session_token = secrets.token_urlsafe(32)
    with closing(_connect()) as connection:
        row = _account(connection, principal.user_id)
        assert row is not None
        with connection:
            connection.execute(
                "INSERT INTO login_sessions (token_hash, user_id, secret_hash, expires_at) "
                "VALUES (?, ?, ?, ?)",
                (sha256(session_token.encode()).hexdigest(), principal.user_id,
                 sha256(row[1].encode()).hexdigest(), int(time.time()) + LOGIN_SECONDS),
            )
    return session_token, principal


def resolve_login(session_token: str | None) -> Principal:
    if not session_token:
        raise HTTPException(status_code=401, detail="请先登录")
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT user_id, secret_hash, expires_at FROM login_sessions WHERE token_hash = ?",
            (sha256(session_token.encode()).hexdigest(),),
        ).fetchone()
        account = _account(connection, row[0]) if row else None
    if row is None or row[2] <= time.time() or account is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    if not compare_digest(row[1], sha256(account[1].encode()).hexdigest()):
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    if account[2]:
        raise HTTPException(status_code=403, detail="账号已停用")
    return Principal(row[0], account[0])


def revoke_login(session_token: str | None) -> None:
    if not session_token:
        return
    with closing(_connect()) as connection:
        with connection:
            connection.execute(
                "DELETE FROM login_sessions WHERE token_hash = ?",
                (sha256(session_token.encode()).hexdigest(),),
            )


def list_users(principal: Principal) -> list[dict[str, str | int | bool]]:
    require_admin(principal)
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT a.user_id, a.role, a.disabled, COUNT(s.session_id) "
            "FROM accounts a LEFT JOIN sessions s ON a.user_id = s.user_id "
            "WHERE a.disabled <> 2 GROUP BY a.user_id ORDER BY a.role, a.user_id"
        ).fetchall()
    return [
        {"user_id": user_id, "role": role, "enabled": not bool(disabled), "sessions": count}
        for user_id, role, disabled, count in rows
    ]


def register_user(user_id: str, password: str) -> None:
    if not _USER_ID.fullmatch(user_id):
        raise HTTPException(status_code=422, detail="用户名无效")
    user_id = user_id.lower()
    if user_id == "admin":
        raise HTTPException(status_code=409, detail="用户名已存在")
    if not 6 <= len(password) <= 128:
        raise HTTPException(status_code=422, detail="密码长度需为 6 到 128 个字符")
    password_hash = _password_hash(password)
    with closing(_connect()) as connection:
        try:
            with connection:
                connection.execute(
                    "INSERT INTO accounts (user_id, role, password_hash, disabled) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, "user", password_hash, 1),
                )
        except mysql.connector.IntegrityError:
            raise HTTPException(status_code=409, detail="用户名已存在") from None


def set_user_enabled(principal: Principal, user_id: str, enabled: bool) -> None:
    require_admin(principal)
    user_id = user_id.lower()
    if user_id == principal.user_id:
        raise HTTPException(status_code=403, detail="不能停用自己的管理员账号")
    with closing(_connect()) as connection:
        with connection:
            account = _account(connection, user_id)
            if account is None or account[2] == 2:
                raise HTTPException(status_code=404, detail="用户不存在")
            connection.execute(
                "UPDATE accounts SET disabled = ? WHERE user_id = ?",
                (int(not enabled), user_id),
            )
            if not enabled:
                connection.execute("DELETE FROM login_sessions WHERE user_id = ?", (user_id,))


def reset_user_password(principal: Principal, user_id: str, password: str) -> None:
    require_admin(principal)
    user_id = user_id.lower()
    if not 6 <= len(password) <= 128:
        raise HTTPException(status_code=422, detail="密码长度需为 6 到 128 个字符")
    password_hash = _password_hash(password)
    with closing(_connect()) as connection:
        with connection:
            account = _account(connection, user_id)
            if account is None or account[2] == 2:
                raise HTTPException(status_code=404, detail="用户不存在")
            updated = connection.execute(
                "UPDATE accounts SET password_hash = ? WHERE user_id = ?",
                (password_hash, user_id),
            )
            if not updated.rowcount:
                raise HTTPException(status_code=404, detail="用户不存在")
            connection.execute("DELETE FROM login_sessions WHERE user_id = ?", (user_id,))


def delete_user(principal: Principal, user_id: str) -> None:
    """Remove access while reserving the name to protect existing Harness history."""
    require_admin(principal)
    user_id = user_id.lower()
    if user_id == principal.user_id:
        raise HTTPException(status_code=403, detail="不能删除自己的管理员账号")
    with closing(_connect()) as connection:
        with connection:
            account = _account(connection, user_id)
            if account is None or account[2] == 2:
                raise HTTPException(status_code=404, detail="用户不存在")
            connection.execute(
                "UPDATE accounts SET disabled = 2, password_hash = ? WHERE user_id = ?",
                ("deleted:" + secrets.token_hex(32), user_id),
            )
            connection.execute("DELETE FROM login_sessions WHERE user_id = ?", (user_id,))


def check_or_create_session(session_id: str, principal: Principal, *, new: bool) -> None:
    with closing(_connect()) as connection:
        with connection:
            if new:
                connection.execute(
                    "INSERT INTO sessions (session_id, user_id) VALUES (?, ?)",
                    (session_id, principal.user_id),
                )
                return
            row = connection.execute(
                "SELECT user_id FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="会话不存在")
            if row[0] != principal.user_id:
                raise HTTPException(status_code=403, detail="无权访问该会话")


def save_message(
    session_id: str, user_id: str, role: str, content: str,
    *, provider: str | None = None, model: str | None = None,
) -> bool:
    """Persist a turn; return False while an existing installation awaits migration."""
    with closing(_connect()) as connection:
        try:
            with connection:
                connection.execute(
                    "INSERT INTO messages "
                    "(session_id, user_id, role, content, provider, model, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (session_id, user_id, role, content, provider, model, int(time.time() * 1000)),
                )
        except mysql.connector.Error as exc:
            if exc.errno == 1146:  # Table is not installed yet; browser cache stays usable.
                return False
            raise
    return True


def _owned_session(connection: DbConnection, session_id: str, principal: Principal) -> None:
    row = connection.execute(
        "SELECT user_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if row[0] != principal.user_id:
        raise HTTPException(status_code=403, detail="无权访问该会话")


def list_messages(session_id: str, principal: Principal) -> list[dict[str, str | int]]:
    with closing(_connect()) as connection:
        _owned_session(connection, session_id, principal)
        try:
            rows = connection.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE session_id = ? AND user_id = ? ORDER BY id",
                (session_id, principal.user_id),
            ).fetchall()
        except mysql.connector.Error as exc:
            if exc.errno == 1146:
                raise HTTPException(status_code=503, detail="服务端历史尚未启用") from None
            raise
    return [
        {"role": role, "content": content, "created_at": created_at}
        for role, content, created_at in rows
    ]


def list_chats(principal: Principal) -> list[dict[str, str | int]]:
    with closing(_connect()) as connection:
        try:
            rows = connection.execute(
                "SELECT s.session_id, m.content, m.provider, m.model, summary.updated_at, "
                "COALESCE(sa.agent_id, 'default'), "
                "COALESCE(se.engine_id, 'dsh-0.1.5rc1') "
                "FROM sessions s JOIN ("
                "SELECT session_id, MIN(id) AS first_id, MAX(created_at) AS updated_at "
                "FROM messages WHERE user_id = ? GROUP BY session_id"
                ") summary ON summary.session_id = s.session_id "
                "JOIN messages m ON m.id = summary.first_id "
                "LEFT JOIN session_agents sa ON sa.session_id = s.session_id "
                "LEFT JOIN session_engines se ON se.session_id = s.session_id "
                "WHERE s.user_id = ? ORDER BY summary.updated_at DESC LIMIT 200",
                (principal.user_id, principal.user_id),
            ).fetchall()
        except mysql.connector.Error as exc:
            if exc.errno == 1146:
                raise HTTPException(status_code=503, detail="服务端历史尚未启用") from None
            raise
    return [
        {
            "session_id": session_id,
            "title": content.replace("\n", " ")[:32],
            "provider": provider or "deepseek-official",
            "model": model or "",
            "agent_id": agent_id,
            "engine_id": engine_id,
            "updated_at": updated_at,
        }
        for session_id, content, provider, model, updated_at, agent_id, engine_id in rows
    ]


def delete_chat(session_id: str, principal: Principal) -> None:
    with closing(_connect()) as connection:
        with connection:
            _owned_session(connection, session_id, principal)
            connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))


