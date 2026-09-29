"""使用真实 API Key 验证 Agent 底座可以完成一轮任务。"""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from app.agent import create_harness
from app.config import AgentConfig, PROJECT_ROOT


class AgentSmokeTest(unittest.TestCase):
    def test_run_completes_with_api_key(self) -> None:
        config = AgentConfig.load()
        if not config.has_api_key:
            self.skipTest("DEEPSEEK_API_KEY is missing; set it in .env")

        workspace_root = PROJECT_ROOT / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="agent-smoke-", dir=workspace_root) as temp:
            test_root = Path(temp)
            test_config = replace(
                config,
                workspace=test_root / "work",
                harness_home=test_root / "harness-home",
            )
            session_id = uuid4().hex

            with create_harness(test_config) as harness:
                result = harness.run(
                    "这是连通性测试。请用一句简短的中文回复，不要调用工具。",
                    session_id=session_id,
                )

            self.assertEqual(result.session_id, session_id)
            turn_ends = [
                event.get("data", {}).get("reason")
                for event in result.events
                if event.get("type") == "turn/end" and isinstance(event.get("data"), dict)
            ]
            failure_detail = (
                f"last_turn_reason={turn_ends[-1] if turn_ends else None!r}; "
                f"final_response={result.final_response[:300]!r}"
            )
            self.assertEqual(result.finish_reason, "completed", failure_detail)
            self.assertTrue(result.final_response.strip(), "Agent 返回了空回复")


if __name__ == "__main__":
    unittest.main()
