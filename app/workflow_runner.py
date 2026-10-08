"""Execute bounded, ordered Agent, MCP and installed DSH plugin-tool steps."""

import asyncio
from dataclasses import replace
import json
import logging
import re
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.agent import create_harness
from app.config import AgentConfig
from app.engines import configure_web_engine, get_engine
from app.extensions import prepare_capabilities
from app.permissions import Principal
from app.platform import get_agent, require_model
from app.trace import summarize_run_events
from app.user_capabilities import effective_capabilities
from app.workflows import (
    finish_run, finish_step, get_run, start_run, start_step, validate_steps,
)


logger = logging.getLogger(__name__)
_TOKEN = re.compile(r"\{\{(input|previous|step[1-8])\}\}")


def _render(value, *, original: str, previous: str, outputs: list[str]):
    """Expand data placeholders without evaluating code or exposing secrets."""
    def lookup(name: str) -> str:
        if name == "input":
            return original
        if name == "previous":
            return previous
        index = int(name[4:]) - 1
        if index >= len(outputs):
            raise HTTPException(422, f"尚无步骤 {index + 1} 的输出")
        return outputs[index]

    if isinstance(value, str):
        return _TOKEN.sub(lambda match: lookup(match.group(1)), value)
    if isinstance(value, list):
        return [_render(item, original=original, previous=previous, outputs=outputs)
                for item in value]
    if isinstance(value, dict):
        return {key: _render(item, original=original, previous=previous, outputs=outputs)
                for key, item in value.items()}
    return value


async def _call_mcp(endpoint: str, tool_name: str, arguments: dict) -> str:
    async with streamablehttp_client(endpoint, timeout=30, sse_read_timeout=60) as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            tools = await session.list_tools()
            if tool_name not in {tool.name for tool in tools.tools}:
                raise HTTPException(422, f"MCP 服务没有工具 {tool_name}")
            result = await session.call_tool(tool_name, arguments)
            if result.isError:
                raise RuntimeError("MCP 工具报告执行失败")
            if getattr(result, "structuredContent", None) is not None:
                return json.dumps(result.structuredContent, ensure_ascii=False)[:16000]
            content = [
                block.text if hasattr(block, "text") else block.model_dump(mode="json")
                for block in result.content
            ]
            return "\n".join(
                item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
                for item in content
            )[:16000]


def _run_agent(
    config: AgentConfig, principal: Principal, step: dict, prompt: str,
    *, provider: str, model: str, api_key: str | None, plugin_tool: str | None = None,
) -> str:
    agent = get_agent(principal, step["agent_id"])
    if plugin_tool:
        # Plugin tools are installed by the operator in this engine's DSH profile.
        instructions = (
            f"必须调用工具 {plugin_tool} 完成当前步骤，随后只总结该工具的实际结果。"
            "如果无法调用该工具，请明确说明失败，不要编造结果。"
        )
        capability_prompt = ""
    else:
        config, capability_prompt, _ = prepare_capabilities(
            config, step["agent_id"], principal
        )
        instructions = step.get("instruction", "")
    parts = [agent["instructions"], capability_prompt, instructions, prompt]
    options = {"provider": provider, "model": model, "isolate_other_keys": True}
    if api_key:
        options["api_key"] = api_key
    options["request_timeout_seconds"] = 180
    with create_harness(config, **options) as harness:
        result = harness.run("\n\n".join(part for part in parts if part),
                             session_id=uuid4().hex)
    if result.finish_reason != "completed" or not (result.final_response or "").strip():
        raise RuntimeError("Agent 没有完成该步骤")
    if plugin_tool:
        trace = summarize_run_events(getattr(result, "events", []))
        if not any(call["name"] == plugin_tool and call["status"] == "completed"
                   for call in trace["tool_calls"]):
            raise RuntimeError("指定插件工具没有成功执行")
    return result.final_response.strip()[:16000]


def execute_workflow(
    principal: Principal, workflow: dict, *, input_text: str,
    provider: str, model: str, api_key: str | None,
    providers_patch: str, chat_patch: str,
) -> dict:
    """Execute in a worker thread; callers serialize it with the user's chat lock."""
    if not input_text.strip() or len(input_text) > 4000:
        raise HTTPException(422, "工作流输入须为 1～4000 个字符")
    if len(api_key or "") > 512:
        raise HTTPException(422, "API Key 长度无效")
    engine = get_engine(workflow["engine_id"])
    steps = validate_steps(principal, engine.engine_id, workflow["steps"])
    needs_model = any(step["kind"] != "mcp_tool" for step in steps)
    if needs_model:
        require_model(principal, provider, model)
        if not api_key and principal.role == "user":
            raise HTTPException(422, "请填写所选模型厂家的 API Key")
    config = configure_web_engine(AgentConfig.load(), principal.user_id, engine)
    if needs_model and not api_key and (provider != "deepseek-official" or not config.has_api_key):
        raise HTTPException(422, "请填写该模型厂家的 API Key")
    config = replace(config, patches=(providers_patch, chat_patch))
    run_id = start_run(principal, workflow, input_text.strip())
    outputs: list[str] = []
    previous = input_text.strip()
    try:
        for index, step in enumerate(steps):
            entered = previous[:16000]
            start_step(run_id, index, step, entered)
            started = monotonic()
            try:
                if step["kind"] == "mcp_tool":
                    capability = next(
                        cap for cap in effective_capabilities(principal, step["agent_id"])
                        if cap["capability_id"] == step["capability_id"] and cap["kind"] == "mcp"
                    )
                    arguments = _render(
                        step["arguments"], original=input_text, previous=previous,
                        outputs=outputs,
                    )
                    output = asyncio.run(_call_mcp(
                        capability["endpoint"], step["tool_name"], arguments,
                    ))
                else:
                    prompt = _render(
                        step.get("instruction", "") or "请处理以下输入，并返回本步骤结果。",
                        original=input_text, previous=previous, outputs=outputs,
                    )
                    prompt += "\n\n本步骤输入：\n" + previous[:16000]
                    output = _run_agent(
                        config, principal, step, prompt, provider=provider, model=model,
                        api_key=api_key,
                        plugin_tool=step["tool_name"] if step["kind"] == "plugin_tool" else None,
                    )
                previous = output[:16000]
                outputs.append(previous)
                finish_step(run_id, index, output=previous,
                            duration_ms=int((monotonic() - started) * 1000))
            except Exception as exc:
                logger.warning("Workflow %s step %s failed: %s", run_id, index, type(exc).__name__)
                message = (str(exc.detail) if isinstance(exc, HTTPException)
                           else "步骤执行失败，请检查 MCP/插件连接和服务日志")
                finish_step(run_id, index, error=message,
                            duration_ms=int((monotonic() - started) * 1000))
                raise RuntimeError(message) from None
        finish_run(run_id, output=previous)
    except Exception as exc:
        finish_run(run_id, error=str(exc))
    return get_run(principal, run_id)
