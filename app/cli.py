"""doctor 检查配置，run 执行一次任务，chat 保持同一个会话。"""

import argparse
import shutil
import sys
from uuid import uuid4

from app.agent import create_harness
from app.config import AgentConfig, PROJECT_ROOT


def _check_key(config: AgentConfig) -> bool:
    if config.has_api_key:
        return True
    print("缺少 DEEPSEEK_API_KEY。请依据你的 .env.example 为 .env，并填入你的密钥。")
    return False


def _print_result(result: object) -> bool:
    print(getattr(result, "final_response", "") or "（Agent 没有返回文字）")
    reason = getattr(result, "finish_reason", None)
    if reason != "completed":
        print(f"[结束原因: {reason or '未知'}]")
    return reason == "completed"


def main() -> int:
    parser = argparse.ArgumentParser(description="可复用的 DeepSeek Harness Agent 底座")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="检查 SDK、目录和密钥配置，不调用模型")

    run = commands.add_parser("run", help="执行一次任务")
    run.add_argument("prompt", help="给 Agent 的任务")
    run.add_argument("--session-id", help="沿用已有会话；默认创建新会话")

    chat = commands.add_parser("chat", help="在同一会话里连续对话；输入 exit 退出")
    chat.add_argument("--session-id", help="沿用已有会话；默认创建新会话")

    args = parser.parse_args()
    try:
        config = AgentConfig.load()
    except ValueError as exc:
        parser.error(str(exc))

    if args.command == "doctor":
        print(f"项目目录: {PROJECT_ROOT}")
        print(f"Python: {sys.version_info.major}.{sys.version_info.minor}")
        print(f"Git: {'已安装' if shutil.which('git') else '未找到'}")
        print(f"模型: {config.model} | Harness profile: {config.profile}")
        print(f"工作目录: {config.workspace}")
        print(f"Harness 数据目录: {config.harness_home}")
        print(f"配置补丁: {len(config.patches)} 个")
        print(f"DeepSeek API Key: {'已配置' if config.has_api_key else '未配置'}")
        print("SDK: 已安装（当前程序已成功导入）")
        return 0

    if not _check_key(config):
        return 2

    session_id = args.session_id or uuid4().hex
    print(f"会话 ID: {session_id}")

    try:
        with create_harness(config) as harness:
            if args.command == "run":
                completed = _print_result(harness.run(args.prompt, session_id=session_id))
                return 0 if completed else 1

            print("开始对话。输入 exit 退出。")
            while True:
                try:
                    prompt = input("你> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if prompt.lower() in {"exit", "quit"}:
                    break
                if not prompt:
                    continue
                _print_result(harness.run(prompt, session_id=session_id))
        return 0
    except Exception as exc:
        print(f"Harness 运行失败: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
