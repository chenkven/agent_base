"""Add a non-destructive Prompt, Skill and local MCP demonstration to MySQL."""

from contextlib import closing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import AgentConfig
from app.permissions import _connect


def main() -> None:
    AgentConfig.load()
    with closing(_connect()) as db:
        with db:
            db.execute(
                "INSERT IGNORE INTO agent_profiles "
                "(agent_id, name, instructions, enabled) VALUES (?, ?, ?, 1)",
                ("demo_agent", "能力演示 Agent", "请清楚地回答用户问题，并标明不确定的信息。"),
            )
            for capability_id, kind, name, content in (
                (
                    "demo_prompt", "prompt", "结构化回答",
                    "回答时使用‘结论、依据、下一步’三个小节；如果信息不足，明确说明。",
                ),
                (
                    "demo-skill", "skill", "信息核对 Skill",
                    "当用户要求总结或核对信息时，先区分已知事实与尚未验证的说法，"
                    "再给出简洁建议。不要编造来源。",
                ),
            ):
                db.execute(
                    "INSERT IGNORE INTO capability_catalog "
                    "(capability_id, kind, name, content, enabled) VALUES (?, ?, ?, ?, 1)",
                    (capability_id, kind, name, content),
                )
                db.execute(
                    "INSERT IGNORE INTO agent_capabilities (agent_id, capability_id) "
                    "VALUES (?, ?)",
                    ("demo_agent", capability_id),
                )
            # Retire the old demo ID: DSH skill names must use kebab-case.
            db.execute(
                "DELETE FROM agent_capabilities "
                "WHERE agent_id = 'demo_agent' AND capability_id = 'demo_skill'"
            )
            db.execute(
                "UPDATE capability_catalog SET enabled = 0 WHERE capability_id = 'demo_skill'"
            )
            db.execute(
                "INSERT IGNORE INTO capability_catalog "
                "(capability_id, kind, name, content, endpoint, enabled) "
                "VALUES (?, 'mcp', ?, '', ?, 1)",
                ("demo_tools", "演示 MCP 工具", "http://127.0.0.1:8000/internal/mcp"),
            )
            db.execute(
                "INSERT IGNORE INTO agent_capabilities (agent_id, capability_id) "
                "VALUES ('demo_agent', 'demo_tools')"
            )
    print("demo_agent 已就绪：Prompt=demo_prompt，Skill=demo-skill，MCP=demo_tools")


if __name__ == "__main__":
    main()
