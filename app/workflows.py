"""Persistent, per-user workflow definitions and execution records."""

from contextlib import closing
import json
import re
import time
from uuid import uuid4

from fastapi import HTTPException
import mysql.connector

from app.engines import get_engine
from app.permissions import Principal, _connect
from app.platform import _database_error, get_agent
from app.user_capabilities import effective_capabilities


_ID = re.compile(r"[0-9a-f]{32}\Z")
_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
MAX_STEPS = 8


def validate_steps(principal: Principal, engine_id: str, steps: list[dict]) -> list[dict]:
    engine = get_engine(engine_id)
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise HTTPException(422, f"工作流需要 1～{MAX_STEPS} 个步骤")
    normalized = []
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise HTTPException(422, f"步骤 {index} 格式错误")
        kind = step.get("kind")
        name = step.get("name", "")
        agent_id = step.get("agent_id", "default")
        if kind not in {"agent", "mcp_tool", "plugin_tool"}:
            raise HTTPException(422, f"步骤 {index} 类型无效")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise HTTPException(422, f"步骤 {index} 名称无效")
        if not isinstance(agent_id, str):
            raise HTTPException(422, f"步骤 {index} Agent 无效")
        get_agent(principal, agent_id)
        item = {"kind": kind, "name": name.strip(), "agent_id": agent_id}
        if kind == "agent":
            instruction = step.get("instruction", "")
            if not isinstance(instruction, str) or len(instruction) > 4000:
                raise HTTPException(422, f"步骤 {index} 指令过长")
            item["instruction"] = instruction.strip()
        elif kind == "mcp_tool":
            capability_id = step.get("capability_id")
            tool_name = step.get("tool_name")
            arguments = step.get("arguments", {})
            if not isinstance(capability_id, str) or not _NAME.fullmatch(capability_id):
                raise HTTPException(422, f"步骤 {index} MCP ID 无效")
            if not isinstance(tool_name, str) or not _NAME.fullmatch(tool_name):
                raise HTTPException(422, f"步骤 {index} 工具名无效")
            if not isinstance(arguments, dict) or len(json.dumps(arguments, ensure_ascii=False)) > 8000:
                raise HTTPException(422, f"步骤 {index} 参数无效或过长")
            available = effective_capabilities(principal, agent_id)
            if not any(cap["capability_id"] == capability_id and cap["kind"] == "mcp"
                       for cap in available):
                raise HTTPException(403, f"步骤 {index} 无权使用该 MCP")
            item.update(capability_id=capability_id, tool_name=tool_name, arguments=arguments)
        else:
            tool_name = step.get("tool_name")
            instruction = step.get("instruction", "")
            if tool_name not in engine.plugin_tools:
                raise HTTPException(403, f"步骤 {index} 插件工具未由该引擎开放")
            if not isinstance(instruction, str) or len(instruction) > 4000:
                raise HTTPException(422, f"步骤 {index} 指令过长")
            item.update(tool_name=tool_name, instruction=instruction.strip())
        normalized.append(item)
    return normalized


def save_workflow(
    principal: Principal, *, workflow_id: str | None, name: str,
    description: str, engine_id: str, steps: list[dict],
) -> str:
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise HTTPException(422, "工作流名称无效")
    if not isinstance(description, str) or len(description) > 500:
        raise HTTPException(422, "工作流描述过长")
    normalized = validate_steps(principal, engine_id, steps)
    if workflow_id is not None and not _ID.fullmatch(workflow_id):
        raise HTTPException(422, "工作流 ID 无效")
    workflow_id = workflow_id or uuid4().hex
    now = int(time.time() * 1000)
    try:
        with closing(_connect()) as db:
            with db:
                existing = db.execute(
                    "SELECT user_id FROM workflows WHERE workflow_id = ? FOR UPDATE",
                    (workflow_id,),
                ).fetchone()
                if existing and existing[0] != principal.user_id:
                    raise HTTPException(404, "工作流不存在")
                if existing:
                    db.execute(
                        "UPDATE workflows SET name = ?, description = ?, engine_id = ?, "
                        "steps_json = ?, updated_at = ? WHERE workflow_id = ?",
                        (name.strip(), description.strip(), engine_id,
                         json.dumps(normalized, ensure_ascii=False), now, workflow_id),
                    )
                else:
                    db.execute(
                        "INSERT INTO workflows "
                        "(workflow_id, user_id, name, description, engine_id, steps_json, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (workflow_id, principal.user_id, name.strip(), description.strip(),
                         engine_id, json.dumps(normalized, ensure_ascii=False), now),
                    )
    except mysql.connector.Error as exc:
        _database_error(exc)
    return workflow_id


def list_workflows(principal: Principal) -> list[dict]:
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT workflow_id, name, description, engine_id, steps_json, updated_at "
                "FROM workflows WHERE user_id = ? ORDER BY updated_at DESC LIMIT 100",
                (principal.user_id,),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"workflow_id": wid, "name": name, "description": description,
         "engine_id": engine_id, "steps": json.loads(steps), "updated_at": updated}
        for wid, name, description, engine_id, steps, updated in rows
    ]


def get_workflow(principal: Principal, workflow_id: str) -> dict:
    if not _ID.fullmatch(workflow_id):
        raise HTTPException(422, "工作流 ID 无效")
    try:
        with closing(_connect()) as db:
            row = db.execute(
                "SELECT name, description, engine_id, steps_json, updated_at "
                "FROM workflows WHERE workflow_id = ? AND user_id = ?",
                (workflow_id, principal.user_id),
            ).fetchone()
    except mysql.connector.Error as exc:
        _database_error(exc)
    if row is None:
        raise HTTPException(404, "工作流不存在")
    return {"workflow_id": workflow_id, "name": row[0], "description": row[1],
            "engine_id": row[2], "steps": json.loads(row[3]), "updated_at": row[4]}


def delete_workflow(principal: Principal, workflow_id: str) -> None:
    get_workflow(principal, workflow_id)
    try:
        with closing(_connect()) as db:
            with db:
                db.execute("DELETE FROM workflows WHERE workflow_id = ? AND user_id = ?",
                           (workflow_id, principal.user_id))
    except mysql.connector.Error as exc:
        _database_error(exc)


def start_run(principal: Principal, workflow: dict, input_text: str) -> str:
    run_id = uuid4().hex
    try:
        with closing(_connect()) as db:
            with db:
                db.execute(
                    "INSERT INTO workflow_runs (run_id, workflow_id, user_id, engine_id, "
                    "status, input_text, started_at) VALUES (?, ?, ?, ?, 'running', ?, ?)",
                    (run_id, workflow["workflow_id"], principal.user_id,
                     workflow["engine_id"], input_text, int(time.time() * 1000)),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)
    return run_id


def start_step(run_id: str, index: int, step: dict, input_text: str) -> None:
    try:
        with closing(_connect()) as db:
            with db:
                db.execute(
                    "INSERT INTO workflow_step_runs "
                    "(run_id, step_index, step_kind, step_name, status, input_text) "
                    "VALUES (?, ?, ?, ?, 'running', ?)",
                    (run_id, index, step["kind"], step["name"], input_text[:60000]),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)


def finish_step(run_id: str, index: int, *, output: str = "", error: str = "",
                duration_ms: int) -> None:
    try:
        with closing(_connect()) as db:
            with db:
                db.execute(
                    "UPDATE workflow_step_runs SET status = ?, output_text = ?, "
                    "error_text = ?, duration_ms = ? WHERE run_id = ? AND step_index = ?",
                    ("failed" if error else "completed", output[:60000], error[:4000],
                     duration_ms, run_id, index),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)


def finish_run(run_id: str, *, output: str = "", error: str = "") -> None:
    try:
        with closing(_connect()) as db:
            with db:
                db.execute(
                    "UPDATE workflow_runs SET status = ?, output_text = ?, error_text = ?, "
                    "finished_at = ? WHERE run_id = ?",
                    ("failed" if error else "completed", output[:60000], error[:4000],
                     int(time.time() * 1000), run_id),
                )
    except mysql.connector.Error as exc:
        _database_error(exc)


def get_run(principal: Principal, run_id: str) -> dict:
    if not _ID.fullmatch(run_id):
        raise HTTPException(422, "运行 ID 无效")
    try:
        with closing(_connect()) as db:
            row = db.execute(
                "SELECT workflow_id, engine_id, status, input_text, output_text, "
                "error_text, started_at, finished_at FROM workflow_runs "
                "WHERE run_id = ? AND user_id = ?",
                (run_id, principal.user_id),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "运行记录不存在")
            steps = db.execute(
                "SELECT step_index, step_kind, step_name, status, input_text, "
                "output_text, error_text, duration_ms FROM workflow_step_runs "
                "WHERE run_id = ? ORDER BY step_index", (run_id,),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return {
        "run_id": run_id, "workflow_id": row[0], "engine_id": row[1],
        "status": row[2], "input": row[3], "output": row[4] or "",
        "error": row[5] or "", "started_at": row[6], "finished_at": row[7],
        "steps": [
            {"index": i, "kind": kind, "name": name, "status": status,
             "input": entered, "output": output or "", "error": error or "",
             "duration_ms": duration}
            for i, kind, name, status, entered, output, error, duration in steps
        ],
    }


def list_runs(principal: Principal, workflow_id: str) -> list[dict]:
    get_workflow(principal, workflow_id)
    try:
        with closing(_connect()) as db:
            rows = db.execute(
                "SELECT run_id, engine_id, status, started_at, finished_at "
                "FROM workflow_runs WHERE workflow_id = ? AND user_id = ? "
                "ORDER BY started_at DESC LIMIT 50",
                (workflow_id, principal.user_id),
            ).fetchall()
    except mysql.connector.Error as exc:
        _database_error(exc)
    return [
        {"run_id": run_id, "engine_id": engine_id, "status": status,
         "started_at": started_at, "finished_at": finished_at}
        for run_id, engine_id, status, started_at, finished_at in rows
    ]
