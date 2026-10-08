"""Capability patch generation and DSH startup without a model request."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from app.agent import create_harness
from app.config import AgentConfig
from app.extensions import prepare_capabilities


class CapabilityTest(unittest.TestCase):
    def test_skill_is_isolated_and_plugin_starts(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = AgentConfig(
                model="deepseek-v4-flash", profile="sdk-minimal", max_tokens=None,
                workspace=base / "workspace", harness_home=base / "harness",
                patches=(
                    (Path(__file__).resolve().parents[1] / "app" / "web_providers.patch.yml").as_posix(),
                    (Path(__file__).resolve().parents[1] / "app" / "web_chat.patch.yml").as_posix(),
                ),
                has_api_key=False,
            )
            skill = {"capability_id": "review_skill", "kind": "skill",
                     "name": "审阅回复", "content": "先检查事实依据。", "endpoint": ""}
            with patch("app.extensions.capabilities_for_agent", return_value=[skill]):
                configured, prompt, fingerprint = prepare_capabilities(config, "reviewer")
            self.assertEqual(prompt, "")
            self.assertEqual(len(fingerprint), 64)
            self.assertIn("先检查事实依据", (
                config.workspace / ".dsh-skills" / "review_skill" / "SKILL.md"
            ).read_text(encoding="utf-8"))
            rows = json.loads(Path(configured.patches[-1]).read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["insert"][1]["config"]["includeDefaultRoots"], False)
            harness = create_harness(configured, api_key="startup-only-key",
                                     provider="deepseek-official", model="deepseek-v4-flash")
            try:
                harness.start()
            finally:
                harness.close()

    def test_mcp_patch_contains_only_assigned_server(self) -> None:
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = AgentConfig(
                model="deepseek-v4-flash", profile="sdk-minimal", max_tokens=None,
                workspace=base / "workspace", harness_home=base / "harness",
                patches=(), has_api_key=False,
            )
            capability = {"capability_id": "demo", "kind": "mcp", "name": "演示",
                          "content": "", "endpoint": "https://example.org/mcp"}
            with patch("app.extensions.capabilities_for_agent", return_value=[capability]):
                configured, _, _ = prepare_capabilities(config, "default")
            rows = json.loads(Path(configured.patches[-1]).read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["insert"][0]["config"]["serverName"], "demo")
            self.assertEqual(rows[0]["insert"][0]["config"]["transport"], "streamable-http")


if __name__ == "__main__":
    unittest.main()
