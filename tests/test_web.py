"""HTTP contract tests without a paid model request."""

from pathlib import Path
from types import SimpleNamespace
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.config import AgentConfig
from app.web import app


class WebTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.config = AgentConfig(
            model="test-model",
            profile="sdk",
            max_tokens=None,
            workspace=Path("workspace"),
            harness_home=Path(".harness"),
            patches=(),
            has_api_key=True,
        )

    def test_page_and_health(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertIn("Agent 底座演示", self.client.get("/").text)

    def test_access_token_is_required(self) -> None:
        with patch.dict(os.environ, {"SERVICE_ACCESS_TOKEN": "test-token"}):
            with patch("app.web.AgentConfig.load", return_value=self.config):
                response = self.client.post("/api/chat", json={"message": "你好"})
        self.assertEqual(response.status_code, 401)

    def test_chat_returns_answer_and_reuses_session(self) -> None:
        fake = MagicMock()
        fake.run.return_value = SimpleNamespace(
            finish_reason="completed", final_response="你好！"
        )
        session_id = "a" * 32
        with patch("app.web._harness", None):
            with patch.dict(os.environ, {"SERVICE_ACCESS_TOKEN": "test-token"}):
                with patch("app.web.AgentConfig.load", return_value=self.config):
                    with patch("app.web.create_harness", return_value=fake) as create:
                        response = self.client.post(
                            "/api/chat",
                            headers={"X-Access-Token": "test-token"},
                            json={"message": "你好", "session_id": session_id},
                        )
                        followup = self.client.post(
                            "/api/chat",
                            headers={"X-Access-Token": "test-token"},
                            json={"message": "继续", "session_id": session_id},
                        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(followup.status_code, 200)
        self.assertEqual(response.json(), {"answer": "你好！", "session_id": session_id})
        self.assertEqual(fake.run.call_count, 2)
        fake.run.assert_any_call("你好", session_id=session_id)
        fake.run.assert_any_call("继续", session_id=session_id)
        fake.start.assert_called_once()
        create.assert_called_once()
        web_config = create.call_args.args[0]
        self.assertEqual(web_config.profile, "sdk-minimal")
        self.assertTrue(web_config.patches[0].endswith("web_chat.patch.yml"))
        self.assertEqual(web_config.harness_home.name, ".harness-web")

    def test_failed_agent_turn_is_reported(self) -> None:
        fake = MagicMock()
        fake.run.return_value = SimpleNamespace(
            finish_reason="error", final_response=""
        )
        with patch("app.web._harness", None):
            with patch.dict(os.environ, {"SERVICE_ACCESS_TOKEN": "test-token"}):
                with patch("app.web.AgentConfig.load", return_value=self.config):
                    with patch("app.web.create_harness", return_value=fake):
                        response = self.client.post(
                            "/api/chat",
                            headers={"X-Access-Token": "test-token"},
                            json={"message": "你好"},
                        )
        self.assertEqual(response.status_code, 502)


if __name__ == "__main__":
    unittest.main()
