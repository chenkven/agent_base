"""Small, safe projection of DSH session events for the chat UI."""

import json


def summarize_run_events(events: list[dict] | None) -> dict[str, list[dict] | list[str]]:
    """Expose tool names and outcomes without leaking arguments or tool output."""
    available: list[str] = []
    calls: list[dict] = []
    by_id: dict[str, dict] = {}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        if event.get("type") == "request/header":
            header = data.get("header")
            tools = header.get("tools") if isinstance(header, dict) else None
            for tool in tools if isinstance(tools, list) else []:
                name = tool.get("name") if isinstance(tool, dict) else None
                if isinstance(name, str) and (name == "skill" or name.startswith("mcp__")):
                    if name not in available and len(available) < 50:
                        available.append(name[:128])
        elif event.get("type") == "tool/call" and len(calls) < 50:
            name = data.get("name")
            call_id = data.get("callId")
            if not isinstance(name, str) or not isinstance(call_id, str):
                continue
            label = name[:128]
            if name == "skill":
                try:
                    arguments = json.loads(data.get("arguments") or "{}")
                except (TypeError, ValueError):
                    arguments = {}
                skill_name = arguments.get("name") if isinstance(arguments, dict) else None
                if isinstance(skill_name, str) and len(skill_name) <= 32:
                    label = f"skill: {skill_name}"
            item = {"name": label, "kind": (
                "mcp" if name.startswith("mcp__") else "skill" if name == "skill" else "tool"
            ), "status": "started"}
            calls.append(item)
            by_id[call_id] = {"item": item, "time": event.get("time")}
        elif event.get("type") == "tool/result":
            message = data.get("message")
            if not isinstance(message, dict):
                continue
            call_id = message.get("toolCallId")
            is_error = message.get("isError")
            if not isinstance(call_id, str):
                blocks = message.get("content")
                block = blocks[0] if isinstance(blocks, list) and blocks else None
                if isinstance(block, dict):
                    call_id = block.get("toolCallId")
                    is_error = block.get("isError")
            entry = by_id.get(call_id) if isinstance(call_id, str) else None
            if entry:
                entry["item"]["status"] = "error" if is_error or data.get("error") else "completed"
                start, end = entry["time"], event.get("time")
                if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                    entry["item"]["duration_ms"] = max(0, round(end - start))
    return {"available_tools": available, "tool_calls": calls}
