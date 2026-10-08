"""控制的 DSH 运行时目录和会话版本绑定."""

from contextlib import closing
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as package_version
import json
from pathlib import Path
import re

from fastapi import HTTPException
import mysql.connector

from app.config import AgentConfig, PROJECT_ROOT
from app.permissions import _connect
from app.platform import _database_error


DEFAULT_ENGINE_ID = "dsh-0.1.5rc1"
_CATALOG = PROJECT_ROOT / "config" / "engines.json"
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_VERSION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._+-]{0,63}\Z")


@dataclass(frozen=True)
class Engine:
    engine_id: str
    name: str
    version: str
    profile: str
    dsh_bin: str | None
    enabled: bool
    plugin_tools: tuple[str, ...]
    available: bool
    status: str

    def public(self) -> dict:
        return {
            "id": self.engine_id, "name": self.name, "version": self.version,
            "profile": self.profile, "enabled": self.enabled,
            "available": self.available, "status": self.status,
            "plugin_tools": list(self.plugin_tools),
        }


def list_engines() -> list[Engine]:
    """Read a server-owned allowlist; browser input never becomes an executable path."""
    try:
        raw = json.loads(_CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(503, f"DSH 引擎目录无法读取：{exc}") from None
    if not isinstance(raw, list):
        raise HTTPException(503, "DSH 引擎目录格式错误")
    engines = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(503, "DSH 引擎配置格式错误")
        engine_id = item.get("id")
        name = item.get("name")
        version = item.get("version")
        profile = item.get("profile", "sdk-minimal")
        binary = item.get("dsh_bin")
        plugin_tools = item.get("plugin_tools", [])
        if (not isinstance(engine_id, str) or not _IDENTIFIER.fullmatch(engine_id)
                or engine_id in seen or not isinstance(name, str) or not name.strip()
                or not isinstance(version, str) or not _VERSION.fullmatch(version)
                or not isinstance(profile, str) or not _IDENTIFIER.fullmatch(profile)
                or binary is not None and not isinstance(binary, str)
                or not isinstance(plugin_tools, list) or any(
                    not isinstance(tool, str) or not _IDENTIFIER.fullmatch(tool)
                    for tool in plugin_tools
                )):
            raise HTTPException(503, "DSH 引擎配置格式错误")
        seen.add(engine_id)
        if binary:
            path = Path(binary)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            path = path.resolve()
            available = path.is_file()
            status = "已安装，首次运行时验证兼容性" if available else "可执行文件不存在"
            binary = str(path)
        else:
            try:
                installed = package_version("deepseek-harness-sdk")
            except PackageNotFoundError:
                installed = ""
            available = installed == version
            status = "已安装" if available else f"当前 SDK 版本为 {installed or '未安装'}"
        engines.append(Engine(
            engine_id, name.strip(), version, profile, binary,
            item.get("enabled") is True, tuple(plugin_tools), available, status,
        ))
    if DEFAULT_ENGINE_ID not in seen:
        raise HTTPException(503, "DSH 引擎目录缺少默认版本")
    return engines


def get_engine(engine_id: str) -> Engine:
    for engine in list_engines():
        if engine.engine_id == engine_id:
            if not engine.enabled or not engine.available:
                raise HTTPException(422, "所选 DSH 引擎尚未启用或安装")
            return engine
    raise HTTPException(422, "未知的 DSH 引擎")


def configure_web_engine(config: AgentConfig, user_id: str, engine: Engine) -> AgentConfig:
    """Keep legacy default paths; keep additional versions in separate homes."""
    workspace = config.workspace.parent / "workspace-web" / user_id
    home = config.harness_home.parent / ".harness-web" / user_id
    if engine.engine_id != DEFAULT_ENGINE_ID:
        workspace = workspace / engine.engine_id
        home = home / engine.engine_id
    return AgentConfig(
        model=config.model, profile=engine.profile, max_tokens=config.max_tokens,
        workspace=workspace, harness_home=home, patches=config.patches,
        has_api_key=config.has_api_key, dsh_bin=engine.dsh_bin,
    )


def bind_session_engine(session_id: str, engine_id: str, *, new: bool) -> None:
    """An existing conversation cannot silently change DSH implementations."""
    try:
        with closing(_connect()) as db:
            with db:
                if new:
                    db.execute(
                        "INSERT INTO session_engines (session_id, engine_id) VALUES (?, ?)",
                        (session_id, engine_id),
                    )
                else:
                    row = db.execute(
                        "SELECT engine_id FROM session_engines WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    original = row[0] if row else DEFAULT_ENGINE_ID
                    if original != engine_id:
                        raise HTTPException(409, "该会话使用其他 DSH 版本，请新建会话")
    except mysql.connector.Error as exc:
        _database_error(exc)
