"""One short local end-to-end web probe; never prints credentials."""

import json
import os
import argparse
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
BASE = "http://127.0.0.1:8000"


def call(path: str, *, method: str = "GET", token: str = "", body: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Session-Token"] = token
    data = json.dumps(body).encode() if body is not None else None
    request = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=200) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        try:
            detail = json.load(exc).get("detail", "请求失败")
        except (ValueError, UnicodeDecodeError):
            detail = "请求失败"
        return exc.code, {"detail": detail}


def main() -> None:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", default="default", help="Agent ID to probe")
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--message", default="请只回复：网页测试成功。")
    parser.add_argument("--expect-tool", default="", help="Fail unless this exact DSH tool name was called")
    parser.add_argument("--expect-answer", default="", help="Fail unless the answer contains this text")
    args = parser.parse_args()
    BASE = args.base.rstrip("/")
    agent_id = args.agent
    password = os.getenv("SERVICE_ACCESS_TOKEN", "")
    if not password:
        raise SystemExit("未配置管理员初始密码，无法自动登录做网页探测")
    status, login = call("/api/login", method="POST", body={
        "username": "admin", "password": password,
    })
    print("login", status)
    if status != 200:
        print("login_detail", login.get("detail", ""))
        return
    token = login["session_token"]
    session_id = None
    try:
        model_status, models = call("/api/models", token=token)
        agent_status, agents = call("/api/agents", token=token)
        print("models", model_status, len(models.get("models", [])))
        print("agents", agent_status, len(agents.get("agents", [])))
        capability_status, capabilities = call(
            f"/api/agents/{agent_id}/capabilities", token=token
        )
        print("capabilities", capability_status,
              [(item["capability_id"], item["kind"])
               for item in capabilities.get("capabilities", [])])
        chat_status, chat = call("/api/chat", method="POST", token=token, body={
            "message": args.message, "provider": "deepseek-official",
            "model": os.getenv("AGENT_MODEL", "deepseek-v4-flash"), "agent_id": agent_id,
        })
        print("chat", chat_status, bool(chat.get("answer")))
        if chat_status == 200:
            print("available_tools", chat.get("available_tools", []))
            print("tool_calls", chat.get("tool_calls", []))
        if chat_status != 200:
            print("chat_detail", chat.get("detail", ""))
        session_id = chat.get("session_id")
        if chat_status != 200:
            raise AssertionError(f"chat returned HTTP {chat_status}")
        if args.expect_tool and args.expect_tool not in {
            item["name"] for item in chat.get("tool_calls", []) if item.get("status") == "completed"
        }:
            raise AssertionError(f"expected completed tool call: {args.expect_tool}")
        if args.expect_answer and args.expect_answer not in chat.get("answer", ""):
            raise AssertionError(f"answer does not contain: {args.expect_answer}")
    finally:
        if session_id:
            deleted, _ = call(f"/api/chat/{session_id}", method="DELETE", token=token)
            print("test_chat_cleanup", deleted)
        logged_out, _ = call("/api/logout", method="POST", token=token)
        print("logout", logged_out)


if __name__ == "__main__":
    main()
