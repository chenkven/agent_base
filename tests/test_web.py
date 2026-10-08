"""Web login, roles and chat ownership without a paid model request."""

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import os
import unittest
from unittest.mock import MagicMock, patch

from dotenv import load_dotenv
from fastapi import HTTPException
from fastapi.testclient import TestClient
import mysql.connector
from deepseek_harness.errors import JsonRpcError

from app.config import AgentConfig, PROJECT_ROOT
from app.agent import create_harness
from app.engines import Engine
from app.permissions import Principal
from app.rate_limit import LoginRateLimiter, SharedLoginRateLimiter
from app.workflow_runner import _run_agent
from app.web import app, _resume_context


class WebTest(unittest.TestCase):
    def setUp(self) -> None:
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        test_database = os.getenv("MYSQL_TEST_DATABASE", "")
        if not test_database.endswith("_test"):
            self.skipTest("未配置独立的 MYSQL_TEST_DATABASE")
        with closing(mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            database=test_database,
            user=os.environ["MYSQL_USER"],
            password=os.environ["MYSQL_PASSWORD"],
        )) as connection:
            cursor = connection.cursor()
            try:
                for table in (
                    "workflow_step_runs", "workflow_runs", "workflows", "session_engines",
                    "user_agent_capabilities", "user_capabilities",
                    "agent_capabilities", "capability_catalog", "user_agent_grants",
                    "login_sessions", "sessions", "accounts",
                ):
                    cursor.execute(f"DELETE FROM {table}")
                cursor.execute("DELETE FROM agent_profiles WHERE agent_id <> 'default'")
                cursor.execute("UPDATE agent_profiles SET name = '通用助手', instructions = '', "
                               "delegate_id = NULL, enabled = 1 WHERE agent_id = 'default'")
                cursor.execute("UPDATE model_catalog SET enabled = 1, user_enabled = 1")
                connection.commit()
            finally:
                cursor.close()
        self.client = TestClient(app)
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        env_patch = patch.dict(os.environ, {
            "MYSQL_DATABASE": test_database,
            "SERVICE_ACCESS_TOKEN": "admin-token",
        })
        env_patch.start()
        self.addCleanup(env_patch.stop)
        harness_patch = patch("app.web._harnesses", {})
        harness_patch.start()
        self.addCleanup(harness_patch.stop)
        key_hash_patch = patch("app.web._harness_settings_hashes", {})
        key_hash_patch.start()
        self.addCleanup(key_hash_patch.stop)
        runtime_sessions_patch = patch("app.web._runtime_sessions", {})
        runtime_sessions_patch.start()
        self.addCleanup(runtime_sessions_patch.stop)
        self.config = AgentConfig(
            model="test-model",
            profile="sdk",
            max_tokens=None,
            workspace=Path(self.temp_dir.name) / "workspace",
            harness_home=Path(self.temp_dir.name) / ".harness",
            patches=(),
            has_api_key=True,
        )
        config_patch = patch("app.web.AgentConfig.load", return_value=self.config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        limiter_patch = patch("app.web._login_limiter", LoginRateLimiter())
        limiter_patch.start()
        self.addCleanup(limiter_patch.stop)

    @staticmethod
    def fake_harness(answer: str = "你好！", reason: str = "completed") -> MagicMock:
        fake = MagicMock()
        fake.run.return_value = SimpleNamespace(
            finish_reason=reason, final_response=answer
        )
        return fake

    def login(self, username: str, password: str) -> str:
        response = self.client.post(
            "/api/login", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["session_token"]

    def register_and_enable(self, username: str, password: str = "abcdef") -> str:
        response = self.client.post(
            "/api/register", json={"username": username, "password": password}
        )
        self.assertEqual(response.status_code, 201)
        admin = self.login("admin", "admin-token")
        enabled = self.client.patch(
            f"/api/admin/users/{username}",
            headers={"X-Session-Token": admin}, json={"enabled": True},
        )
        self.assertEqual(enabled.status_code, 200)
        return self.login(username, password)

    def post_chat(
        self, token: str, message: str, session_id: str | None = None,
        api_key: str | None = "user-test-key",
        provider: str = "deepseek-official", model: str | None = None,
        agent_id: str = "default", engine_id: str = "dsh-0.1.5rc1",
    ):
        return self.client.post(
            "/api/chat", headers={"X-Session-Token": token},
            json={"message": message, "session_id": session_id, "api_key": api_key,
                  "provider": provider, "model": model, "agent_id": agent_id,
                  "engine_id": engine_id},
        )

    def test_bootstrap_keeps_agent_rules_scoped_and_caches_static_assets(self) -> None:
        alice = self.register_and_enable("alice")
        admin = self.login("admin", "admin-token")
        headers = {"X-Session-Token": admin}
        response = self.client.put(
            "/api/admin/agents/private-agent", headers=headers,
            json={"name": "Private", "instructions": "仅管理员规则"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get("/api/bootstrap").status_code, 401)
        bootstrap = self.client.get(
            "/api/bootstrap", headers={"X-Session-Token": alice}
        )
        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        data = bootstrap.json()
        self.assertEqual(data["user"], {"user_id": "alice", "role": "user"})
        self.assertEqual([agent["agent_id"] for agent in data["agents"]], ["default"])
        self.assertEqual(data["initial_agent"]["agent"]["agent_id"], "default")
        self.assertNotIn("仅管理员规则", bootstrap.text)
        login = self.client.post(
            "/api/login", json={"username": "alice", "password": "abcdef"}
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["bootstrap"]["user"], data["user"])
        self.assertNotIn("仅管理员规则", login.text)
        static = self.client.get("/static/chat.js?v=platform-7")
        self.assertEqual(static.status_code, 200)
        self.assertIn("max-age=3600", static.headers["cache-control"])

    def test_page_and_health(self) -> None:
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        with patch("app.web.check_database_ready") as probe:
            self.assertEqual(self.client.get("/ready").json(), {"status": "ready"})
            probe.assert_called_once_with()
        self.assertIn("注册", self.client.get("/").text)
        self.assertIn('minlength="6"', self.client.get("/").text)
        self.assertEqual(self.client.get("/static/site.css").status_code, 200)
        self.assertIn("管理工作台", self.client.get("/app").text)
        self.assertIn('id="workflow-engine"', self.client.get("/workflows").text)
        self.assertIn('id="engine-list"', self.client.get("/engines").text)
        self.assertEqual(self.client.get("/static/workflows.js").status_code, 200)

    def test_startup_loads_env_before_cached_chat(self) -> None:
        with patch("app.web.AgentConfig.load") as load:
            with TestClient(app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
            load.assert_called_once_with()
        self.assertIn('id="admin-dialog"', self.client.get("/app").text)
        self.assertEqual(self.client.get("/static/workbench.css").status_code, 200)
        self.assertIn('id="model-api-key"', self.client.get("/app").text)
        self.assertIn('value="qwen-bailian"', self.client.get("/app").text)
        self.assertIn('id="model-preset"', self.client.get("/app").text)

    def test_history_routes_require_login_and_own_the_session(self) -> None:
        alice = self.register_and_enable("alice")
        bob = self.register_and_enable("bob")
        with patch("app.web.create_harness", return_value=self.fake_harness()):
            session_id = self.post_chat(alice, "第一条").json()["session_id"]
        path = f"/api/chat/{session_id}/messages"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(
            self.client.get(path, headers={"X-Session-Token": bob}).status_code, 403
        )
        with patch("app.web.list_messages", return_value=[
            {"role": "user", "content": "第一条", "created_at": 1},
            {"role": "assistant", "content": "你好！", "created_at": 2},
        ]):
            response = self.client.get(path, headers={"X-Session-Token": alice})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["messages"]), 2)
        with patch("app.web.list_chats", return_value=[{"session_id": session_id}]):
            response = self.client.get("/api/chats", headers={"X-Session-Token": alice})
        self.assertEqual(response.json()["chats"][0]["session_id"], session_id)
        self.assertEqual(
            self.client.delete(f"/api/chat/{session_id}", headers={"X-Session-Token": bob}).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(f"/api/chat/{session_id}", headers={"X-Session-Token": alice}).status_code,
            200,
        )

    def test_chat_history_is_saved_in_mysql(self) -> None:
        alice = self.register_and_enable("alice")
        with patch("app.web.create_harness", return_value=self.fake_harness("服务端回复")):
            response = self.post_chat(alice, "历史测试")
        self.assertEqual(response.status_code, 200)
        session_id = response.json()["session_id"]
        headers = {"X-Session-Token": alice}
        chats = self.client.get("/api/chats", headers=headers)
        self.assertEqual(chats.status_code, 200)
        self.assertEqual(chats.json()["chats"][0]["session_id"], session_id)
        messages = self.client.get(f"/api/chat/{session_id}/messages", headers=headers)
        self.assertEqual(messages.status_code, 200)
        self.assertEqual(
            [(item["role"], item["content"]) for item in messages.json()["messages"]],
            [("user", "历史测试"), ("assistant", "服务端回复")],
        )

    def test_login_limit_is_shared_through_mysql(self) -> None:
        limiter = SharedLoginRateLimiter()
        another_worker = SharedLoginRateLimiter()
        ip, username = "198.51.100.17", "missing-shared-user"
        limiter.success(ip, username)
        try:
            for _ in range(5):
                limiter.check(ip, username)
                limiter.failure(ip, username)
            with self.assertRaises(HTTPException) as blocked:
                another_worker.check(ip, username)
            self.assertEqual(blocked.exception.status_code, 429)
        finally:
            limiter.success(ip, username)

    def test_register_approve_and_delete_user(self) -> None:
        self.assertEqual(
            self.client.post("/api/register", json={"username": "short", "password": "12345"}).status_code,
            422,
        )
        registered = self.client.post(
            "/api/register", json={"username": "NewUser", "password": "123456"}
        )
        self.assertEqual(registered.status_code, 201)
        self.assertEqual(registered.json(), {"user_id": "newuser", "status": "pending_approval"})
        self.assertEqual(
            self.client.post("/api/login", json={"username": "newuser", "password": "123456"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/register", json={"username": "Admin", "password": "123456"}).status_code,
            409,
        )
        admin = self.login("admin", "admin-token")
        admin_headers = {"X-Session-Token": admin}
        users = self.client.get("/api/admin/users", headers=admin_headers).json()["users"]
        self.assertFalse(next(user for user in users if user["user_id"] == "newuser")["enabled"])
        self.assertEqual(
            self.client.patch("/api/admin/users/newuser", headers=admin_headers,
                              json={"enabled": True}).status_code,
            200,
        )
        user_token = self.login("NEWUSER", "123456")
        self.assertEqual(
            self.client.delete("/api/admin/users/admin", headers={"X-Session-Token": user_token}).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete("/api/admin/users/newuser", headers=admin_headers).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/me", headers={"X-Session-Token": user_token}).status_code, 401)
        self.assertEqual(
            self.client.post("/api/login", json={"username": "newuser", "password": "123456"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/api/register", json={"username": "newuser", "password": "123456"}).status_code,
            409,
        )
        self.assertNotIn(
            "newuser", [user["user_id"] for user in self.client.get("/api/admin/users", headers=admin_headers).json()["users"]],
        )
        self.assertEqual(
            self.client.delete("/api/admin/users/admin", headers=admin_headers).status_code,
            403,
        )

    def test_login_role_and_admin_user_management(self) -> None:
        alice = self.register_and_enable("alice")
        self.register_and_enable("bob")
        admin = self.login("admin", "admin-token")
        alice_headers = {"X-Session-Token": alice}
        admin_headers = {"X-Session-Token": admin}
        self.assertEqual(self.client.get("/api/me", headers=alice_headers).json(), {"user_id": "alice", "role": "user"})
        self.assertEqual(self.client.get("/api/admin/users", headers=alice_headers).status_code, 403)
        self.assertEqual(
            self.client.patch("/api/admin/users/bob", headers=alice_headers,
                              json={"enabled": False}).status_code,
            403,
        )
        users = self.client.get("/api/admin/users", headers=admin_headers).json()["users"]
        self.assertEqual([user["user_id"] for user in users], ["admin", "alice", "bob"])
        self.assertEqual(
            self.client.patch("/api/admin/users/alice", headers=admin_headers,
                              json={"enabled": False}).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/me", headers=alice_headers).status_code, 401)
        self.assertEqual(
            self.client.patch("/api/admin/users/admin", headers=admin_headers,
                              json={"enabled": False}).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch("/api/admin/users/alice", headers=admin_headers,
                              json={"enabled": True}).status_code,
            200,
        )
        new_alice = self.login("alice", "abcdef")
        self.assertEqual(self.client.get("/api/me", headers={"X-Session-Token": new_alice}).status_code, 200)
        self.client.post("/api/logout", headers={"X-Session-Token": new_alice})
        self.assertEqual(self.client.get("/api/me", headers={"X-Session-Token": new_alice}).status_code, 401)

    def test_database_password_hash_and_reset(self) -> None:
        charlie = self.register_and_enable("charlie")
        admin = self.login("admin", "admin-token")
        with closing(mysql.connector.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            database=os.environ["MYSQL_TEST_DATABASE"],
            user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        )) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SELECT password_hash FROM accounts WHERE user_id = %s", ("charlie",))
                stored = cursor.fetchone()[0]
            finally:
                cursor.close()
        self.assertTrue(stored.startswith("scrypt:"))
        self.assertNotIn("abcdef", stored)
        with patch.dict(os.environ, {"SERVICE_ACCESS_TOKEN": ""}):
            self.login("admin", "admin-token")
            self.assertEqual(
                self.client.put("/api/admin/users/charlie/password",
                                headers={"X-Session-Token": charlie},
                                json={"password": "123456"}).status_code,
                403,
            )
            self.assertEqual(
                self.client.put("/api/admin/users/charlie/password",
                                headers={"X-Session-Token": admin},
                                json={"password": "12345"}).status_code,
                422,
            )
            self.assertEqual(
                self.client.put("/api/admin/users/charlie/password",
                                headers={"X-Session-Token": admin},
                                json={"password": "123456"}).status_code,
                200,
            )
            self.assertEqual(self.client.get("/api/me", headers={"X-Session-Token": charlie}).status_code, 401)
            self.assertEqual(
                self.client.post("/api/login", json={"username": "charlie", "password": "abcdef"}).status_code,
                401,
            )
            self.login("charlie", "123456")

    def test_session_token_is_required(self) -> None:
        self.assertEqual(self.client.post("/api/chat", json={"message": "你好"}).status_code, 401)
        self.assertEqual(self.post_chat("wrong-token", "你好").status_code, 401)
        self.assertEqual(
            self.client.get("/api/me", headers={"X-Access-Token": "admin-token"}).status_code,
            401,
        )
        self.assertEqual(self.client.post("/api/login", json={"access_token": "admin-token"}).status_code, 422)

    def test_login_rate_limit(self) -> None:
        for _ in range(5):
            response = self.client.post(
                "/api/login", json={"username": "admin", "password": "wrong"}
            )
            self.assertEqual(response.status_code, 401)
        blocked = self.client.post(
            "/api/login", json={"username": "admin", "password": "admin-token"}
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("稍后再试", blocked.json()["detail"])

    def test_user_must_supply_own_key(self) -> None:
        alice = self.register_and_enable("alice")
        self.assertEqual(self.post_chat(alice, "你好", api_key=None).status_code, 422)
        self.assertEqual(self.post_chat(alice, "你好", api_key="  ").status_code, 422)
        with patch("app.web.create_harness", return_value=self.fake_harness()) as create:
            response = self.post_chat(alice, "你好", api_key=" user-owned-key ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(create.call_args.kwargs["api_key"], "user-owned-key")
        self.assertNotIn("user-owned-key", str(response.json()))

    def test_admin_uses_server_key(self) -> None:
        admin = self.login("admin", "admin-token")
        with patch("app.web.create_harness", return_value=self.fake_harness()) as create:
            response = self.post_chat(admin, "你好", api_key=None)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(create.call_args.kwargs, {
            "provider": "deepseek-official", "model": "test-model",
            "isolate_other_keys": True,
        })

    def test_harness_forwards_user_key_to_sdk(self) -> None:
        with patch("app.agent.DeepSeekHarness") as harness_class:
            create_harness(self.config, api_key="user-owned-key")
        self.assertEqual(harness_class.call_args.kwargs["api_key"], "user-owned-key")

    def test_other_provider_uses_own_key_and_model(self) -> None:
        alice = self.register_and_enable("alice")
        self.assertEqual(
            self.post_chat(alice, "hello", provider="openai", model=None).status_code, 422
        )
        self.assertEqual(
            self.post_chat(alice, "hello", provider="unknown", model="x").status_code, 422
        )
        self.assertEqual(
            self.post_chat(alice, "hello", provider="openai", model="gpt-4.1-mini", api_key=None).status_code,
            422,
        )
        unknown_model_harness = self.fake_harness()
        unknown_model_harness.start.side_effect = JsonRpcError(
            -32603, 'pi-ai provider "zai" has no configured model "bad-model"'
        )
        with patch("app.web.create_harness", return_value=unknown_model_harness):
            unknown_model = self.post_chat(alice, "hello", provider="zai", model="bad-model")
        self.assertEqual(unknown_model.status_code, 422)
        self.assertIn("模型 ID", unknown_model.json()["detail"])
        with patch("app.web.create_harness", return_value=self.fake_harness()) as create:
            response = self.post_chat(alice, "hello", provider="openai", model="gpt-4.1-mini")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(create.call_args.kwargs, {
            "provider": "openai", "model": "gpt-4.1-mini", "api_key": "user-test-key",
            "isolate_other_keys": True,
        })
        self.assertTrue(create.call_args.args[0].patches[0].endswith("web_providers.patch.yml"))
        with patch("app.agent.DeepSeekHarness") as harness_class:
            create_harness(self.config, api_key="user-owned-key", provider="openai", model="gpt-4.1-mini")
        self.assertEqual(harness_class.call_args.kwargs["provider"], "openai")
        self.assertEqual(harness_class.call_args.kwargs["model"], "gpt-4.1-mini")
        self.assertEqual(harness_class.call_args.kwargs["env"]["USER_MODEL_API_KEY"], "user-owned-key")
        self.assertEqual(harness_class.call_args.kwargs["env"]["DEEPSEEK_API_KEY"], "")
        self.assertEqual(harness_class.call_args.kwargs["env"]["OPENAI_API_KEY"], "")
        self.assertEqual(harness_class.call_args.kwargs["env"]["DASHSCOPE_API_KEY"], "")
        self.assertIsNone(harness_class.call_args.kwargs["api_key"])

        with patch("app.web.create_harness", return_value=self.fake_harness()) as qwen_create:
            qwen = self.post_chat(alice, "你好", provider="qwen-bailian", model="qwen-plus")
        self.assertEqual(qwen.status_code, 200)
        self.assertEqual(qwen_create.call_args.kwargs["provider"], "qwen-bailian")
        self.assertEqual(qwen_create.call_args.kwargs["model"], "qwen-plus")

    def test_chat_reuses_own_session(self) -> None:
        alice = self.register_and_enable("alice")
        fake = self.fake_harness()
        with patch("app.web.create_harness", return_value=fake) as create:
            response = self.post_chat(alice, "你好")
            session_id = response.json()["session_id"]
            followup = self.post_chat(alice, "继续", session_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(followup.status_code, 200)
        self.assertEqual(response.json(), {
            "answer": "你好！", "session_id": session_id,
            "available_tools": [], "tool_calls": [],
            "engine_id": "dsh-0.1.5rc1",
        })
        fake.run.assert_any_call("你好", session_id=session_id)
        fake.run.assert_any_call("继续", session_id=session_id)
        self.assertEqual(fake.start.call_count, 1)
        self.assertEqual(fake.close.call_count, 0)
        self.assertEqual(create.call_count, 1)
        web_config = create.call_args.args[0]
        self.assertEqual(
            [call.kwargs["api_key"] for call in create.call_args_list],
            ["user-test-key"],
        )
        self.assertEqual(web_config.profile, "sdk-minimal")
        self.assertTrue(web_config.patches[-1].endswith("web_chat.patch.yml"))
        self.assertEqual(web_config.harness_home.name, "alice")
        self.assertEqual(web_config.workspace.name, "alice")

        logged_out = self.client.post("/api/logout", headers={"X-Session-Token": alice})
        self.assertEqual(logged_out.status_code, 200)
        self.assertEqual(fake.close.call_count, 1)

    def test_different_users_run_concurrently(self) -> None:
        alice = self.register_and_enable("alice")
        bob = self.register_and_enable("bob")
        alice_started = Event()
        allow_alice_finish = Event()

        def make_harness(config, **_kwargs):
            fake = self.fake_harness()
            if config.workspace.name == "alice":
                def run_alice(*_args, **_kwargs):
                    alice_started.set()
                    if not allow_alice_finish.wait(10):
                        raise TimeoutError("Alice's test request was not released")
                    return SimpleNamespace(finish_reason="completed", final_response="Alice 完成")
                fake.run.side_effect = run_alice
            return fake

        with patch("app.web.create_harness", side_effect=make_harness):
            with ThreadPoolExecutor(max_workers=2) as executor:
                alice_future = executor.submit(self.post_chat, alice, "慢任务")
                try:
                    self.assertTrue(alice_started.wait(5))
                    bob_future = executor.submit(self.post_chat, bob, "快任务")
                    self.assertEqual(bob_future.result(timeout=5).status_code, 200)
                finally:
                    allow_alice_finish.set()
                self.assertEqual(alice_future.result(timeout=5).status_code, 200)

    def test_busy_user_is_rejected_without_waiting_for_worker(self) -> None:
        alice = self.register_and_enable("alice")
        started = Event()
        release = Event()
        fake = self.fake_harness()

        def slow_run(*_args, **_kwargs):
            started.set()
            if not release.wait(10):
                raise TimeoutError("Test request was not released")
            return SimpleNamespace(finish_reason="completed", final_response="完成")

        fake.run.side_effect = slow_run
        with patch("app.web.create_harness", return_value=fake):
            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(self.post_chat, alice, "慢任务")
                try:
                    self.assertTrue(started.wait(5))
                    busy = self.post_chat(alice, "同时再发")
                    self.assertEqual(busy.status_code, 429)
                    self.assertIn("正在处理", busy.json()["detail"])
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=5).status_code, 200)

    def test_chat_timeout_closes_harness(self) -> None:
        alice = self.register_and_enable("alice")
        release = Event()
        fake = self.fake_harness()
        fake.run.side_effect = lambda *_args, **_kwargs: (
            release.wait(5), SimpleNamespace(finish_reason="completed", final_response="太晚了")
        )[1]
        fake.close.side_effect = release.set
        with patch("app.web.create_harness", return_value=fake), patch(
            "app.web._chat_timeout_seconds", return_value=0.05
        ):
            response = self.post_chat(alice, "慢任务")
        self.assertEqual(response.status_code, 504)
        self.assertTrue(fake.close.called)

    def test_harness_start_shares_chat_timeout(self) -> None:
        alice = self.register_and_enable("alice")
        release = Event()
        fake = self.fake_harness()
        fake.start.side_effect = lambda: release.wait(5)
        fake.close.side_effect = release.set
        with patch("app.web.create_harness", return_value=fake), patch(
            "app.web._chat_timeout_seconds", return_value=0.05
        ):
            response = self.post_chat(alice, "慢启动")
        self.assertEqual(response.status_code, 504)
        fake.run.assert_not_called()
        self.assertTrue(fake.close.called)

    def test_changed_key_requires_new_session(self) -> None:
        alice = self.register_and_enable("alice")
        first_harness = self.fake_harness()
        second_harness = self.fake_harness()
        with patch("app.web.create_harness", side_effect=[first_harness, second_harness]) as create:
            first = self.post_chat(alice, "hello")
            session_id = first.json()["session_id"]
            changed = self.post_chat(alice, "continue", session_id, api_key="rotated-user-key")
            fresh = self.post_chat(alice, "hello again", api_key="rotated-user-key")
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(fresh.status_code, 200)
        self.assertNotEqual(fresh.json()["session_id"], session_id)
        self.assertEqual(first_harness.close.call_count, 1)
        self.assertEqual(create.call_count, 2)

    def test_changed_provider_requires_new_session(self) -> None:
        alice = self.register_and_enable("alice")
        first_harness = self.fake_harness()
        second_harness = self.fake_harness()
        with patch("app.web.create_harness", side_effect=[first_harness, second_harness]):
            first = self.post_chat(alice, "hello")
            session_id = first.json()["session_id"]
            changed_model = self.post_chat(alice, "continue", session_id, model="deepseek-v4-pro")
            changed = self.post_chat(
                alice, "continue", session_id, provider="openai", model="gpt-4.1-mini"
            )
            fresh = self.post_chat(alice, "hello again", provider="openai", model="gpt-4.1-mini")
        self.assertEqual(changed_model.status_code, 409)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(fresh.status_code, 200)
        self.assertEqual(first_harness.close.call_count, 1)

    def test_users_cannot_continue_each_others_sessions(self) -> None:
        alice = self.register_and_enable("alice")
        bob = self.register_and_enable("bob")
        with patch("app.web.create_harness", side_effect=[self.fake_harness(), self.fake_harness()]) as create:
            created = self.post_chat(alice, "你好")
            session_id = created.json()["session_id"]
            denied = self.post_chat(bob, "继续", session_id)
            unknown = self.post_chat(bob, "继续", "f" * 32)
            bob_chat = self.post_chat(bob, "你好")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(bob_chat.status_code, 200)
        self.assertEqual(create.call_count, 2)
        self.assertNotEqual(
            create.call_args_list[0].args[0].harness_home,
            create.call_args_list[1].args[0].harness_home,
        )

    def test_old_session_after_harness_restart_replays_completed_history(self) -> None:
        alice = self.register_and_enable("alice")
        bob = self.register_and_enable("bob")
        with patch("app.web.create_harness", return_value=self.fake_harness()):
            first = self.post_chat(alice, "你好")
        session_id = first.json()["session_id"]
        restarted = self.fake_harness("继续成功")
        with patch("app.web._harnesses", {}), patch("app.web._harness_settings_hashes", {}), \
                patch("app.web._runtime_sessions", {}):
            with patch("app.web.create_harness", return_value=restarted):
                continued = self.post_chat(alice, "继续", session_id)
                continued_again = self.post_chat(alice, "再问", session_id)
                denied = self.post_chat(bob, "继续", session_id)
        self.assertEqual(continued.status_code, 200, continued.text)
        self.assertEqual(continued_again.status_code, 200, continued_again.text)
        self.assertEqual(continued.json()["session_id"], session_id)
        replayed_prompt = restarted.run.call_args_list[0].args[0]
        self.assertIn("你好", replayed_prompt)
        self.assertIn("你好！", replayed_prompt)
        self.assertIn("继续", replayed_prompt)
        runtime_id = restarted.run.call_args_list[0].kwargs["session_id"]
        self.assertNotEqual(runtime_id, session_id)
        self.assertEqual(restarted.run.call_args_list[1].args[0], "再问")
        self.assertEqual(restarted.run.call_args_list[1].kwargs["session_id"], runtime_id)
        self.assertEqual(denied.status_code, 403)

    def test_replay_excludes_unanswered_messages(self) -> None:
        context = _resume_context([
            {"role": "user", "content": "记住苹果"},
            {"role": "assistant", "content": "记住了"},
            {"role": "user", "content": "这轮失败了"},
        ])
        self.assertIn("记住苹果", context)
        self.assertIn("记住了", context)
        self.assertNotIn("这轮失败了", context)

    def test_failed_agent_turn_is_reported(self) -> None:
        admin = self.login("admin", "admin-token")
        with patch("app.web.create_harness", return_value=self.fake_harness("", "error")):
            response = self.post_chat(admin, "你好")
        self.assertEqual(response.status_code, 502)

    def test_model_catalog_is_enforced_by_server(self) -> None:
        alice = self.register_and_enable("alice")
        admin = self.login("admin", "admin-token")
        path = "/api/admin/models/deepseek-official/test-model"
        self.assertEqual(self.client.put(path, headers={"X-Session-Token": alice},
                                         json={"enabled": False}).status_code, 403)
        changed = self.client.put(
            path, headers={"X-Session-Token": admin},
            json={"enabled": True, "user_enabled": False},
        )
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(any(item["model_id"] == "test-model" for item in
                             self.client.get("/api/models", headers={"X-Session-Token": alice})
                             .json()["models"]))
        self.assertEqual(self.post_chat(alice, "你好").status_code, 403)
        with patch("app.web.create_harness", return_value=self.fake_harness()):
            self.assertEqual(self.post_chat(admin, "你好", api_key=None).status_code, 200)

    def test_agent_grant_and_two_harness_collaboration(self) -> None:
        alice = self.register_and_enable("alice")
        admin = self.login("admin", "admin-token")
        headers = {"X-Session-Token": admin}
        for agent_id, body in (
            ("reviewer", {"name": "审阅员", "instructions": "指出风险", "enabled": True}),
            ("lead", {"name": "主 Agent", "instructions": "总结分析",
                      "delegate_id": "reviewer", "enabled": True}),
        ):
            response = self.client.put(f"/api/admin/agents/{agent_id}",
                                       headers=headers, json=body)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.post_chat(alice, "检查一下", agent_id="lead").status_code, 403)
        granted = self.client.put(
            "/api/admin/users/alice/agents/lead", headers=headers, json={"granted": True}
        )
        self.assertEqual(granted.status_code, 200)
        self.assertEqual(
            [item["agent_id"] for item in self.client.get(
                "/api/agents", headers={"X-Session-Token": alice}).json()["agents"]],
            ["default", "lead"],
        )
        child = self.fake_harness("发现一处风险")
        main = self.fake_harness("已总结")
        with patch("app.web.create_harness", side_effect=[main, child]) as create:
            response = self.post_chat(alice, "检查一下", agent_id="lead")
            session_id = response.json()["session_id"]
            switched = self.post_chat(alice, "继续", session_id, agent_id="default")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(switched.status_code, 409)
        self.assertEqual(create.call_count, 2)
        self.assertEqual(create.call_args_list[0].args[0].workspace.name, "alice")
        self.assertEqual(create.call_args_list[1].args[0].workspace.name, "reviewer")
        self.assertIn("发现一处风险", main.run.call_args.args[0])
        self.assertTrue(child.close.called)
        self.assertEqual(self.post_chat(alice, "检查一下", agent_id="reviewer").status_code, 403)

    def test_users_manage_separate_personal_prompts(self) -> None:
        alice = self.register_and_enable("alice")
        bob = self.register_and_enable("bob")
        endpoint = "/api/my/capabilities/same-id"
        for token, content in ((alice, "Alice 的私人规则"), (bob, "Bob 的私人规则")):
            saved = self.client.put(endpoint, headers={"X-Session-Token": token},
                                    json={"kind": "prompt", "name": "私人规则", "content": content})
            self.assertEqual(saved.status_code, 200, saved.text)
            assigned = self.client.put(
                "/api/my/agents/default/capabilities/same-id",
                headers={"X-Session-Token": token}, json={"assigned": True},
            )
            self.assertEqual(assigned.status_code, 200, assigned.text)
        alice_caps = self.client.get("/api/my/capabilities", headers={"X-Session-Token": alice})
        bob_caps = self.client.get("/api/my/capabilities", headers={"X-Session-Token": bob})
        self.assertEqual(alice_caps.json()["capabilities"][0]["content"], "Alice 的私人规则")
        self.assertEqual(bob_caps.json()["capabilities"][0]["content"], "Bob 的私人规则")
        first, second = self.fake_harness(), self.fake_harness()
        with patch("app.web.create_harness", side_effect=[first, second]):
            self.assertEqual(self.post_chat(alice, "你好").status_code, 200)
            self.assertEqual(self.post_chat(bob, "你好").status_code, 200)
        self.assertIn("Alice 的私人规则", first.run.call_args.args[0])
        self.assertNotIn("Bob 的私人规则", first.run.call_args.args[0])
        self.assertIn("Bob 的私人规则", second.run.call_args.args[0])
        self.assertNotIn("Alice 的私人规则", second.run.call_args.args[0])

    def test_personal_mcp_requires_admin_approval_and_resets_on_url_change(self) -> None:
        alice = self.register_and_enable("alice")
        admin = self.login("admin", "admin-token")
        path = "/api/my/capabilities/private-mcp"
        body = {"kind": "mcp", "name": "个人服务", "endpoint": "https://example.com/mcp"}
        self.assertEqual(self.client.put(path, headers={"X-Session-Token": alice},
                                         json=body).status_code, 200)
        self.assertEqual(self.client.put(
            "/api/my/agents/default/capabilities/private-mcp",
            headers={"X-Session-Token": alice}, json={"assigned": True},
        ).status_code, 200)
        visible = "/api/agents/default/capabilities"
        headers = {"X-Session-Token": alice}
        self.assertEqual(self.client.get(visible, headers=headers).json()["capabilities"], [])
        approve = "/api/admin/users/alice/mcps/private-mcp/approval"
        self.assertEqual(self.client.put(approve, headers=headers,
                                         json={"approved": True}).status_code, 403)
        admin_headers = {"X-Session-Token": admin}
        self.assertFalse(self.client.get("/api/admin/user-mcps", headers=admin_headers)
                         .json()["mcps"][0]["approved"])
        self.assertEqual(self.client.put(approve, headers=admin_headers,
                                         json={"approved": True}).status_code, 200)
        self.assertEqual(self.client.put(approve, headers=admin_headers,
                                         json={"approved": True}).status_code, 200)
        self.assertEqual(len(self.client.get(visible, headers=headers)
                             .json()["capabilities"]), 1)
        body["endpoint"] = "https://example.org/mcp"
        self.assertEqual(self.client.put(path, headers=headers, json=body).status_code, 200)
        self.assertEqual(self.client.get(visible, headers=headers).json()["capabilities"], [])

    def test_capability_assignment_controls_prompt_and_skill_patch(self) -> None:
        alice = self.register_and_enable("alice")
        admin = self.login("admin", "admin-token")
        headers = {"X-Session-Token": admin}
        self.assertEqual(self.client.get(
            "/api/admin/capabilities", headers={"X-Session-Token": alice}
        ).status_code, 403)
        self.assertEqual(self.client.get(
            "/api/agents/default/capabilities"
        ).status_code, 401)
        for capability_id, kind, content in (
            ("tone", "prompt", "使用简洁语言。"),
            ("review", "skill", "先核对事实，再给出建议。"),
        ):
            response = self.client.put(
                f"/api/admin/capabilities/{capability_id}", headers=headers,
                json={"kind": kind, "name": capability_id, "content": content},
            )
            self.assertEqual(response.status_code, 200, response.text)
            assigned = self.client.put(
                f"/api/admin/agents/default/capabilities/{capability_id}", headers=headers,
                json={"assigned": True},
            )
            self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(self.client.put(
            "/api/admin/capabilities/remote", headers=headers,
            json={"kind": "mcp", "name": "remote", "endpoint": "file:///etc/passwd"},
        ).status_code, 422)
        self.assertEqual(self.client.put(
            "/api/admin/capabilities/invalid_skill", headers=headers,
            json={"kind": "skill", "name": "invalid", "content": "测试"},
        ).status_code, 422)
        self.assertEqual(self.client.put(
            "/api/admin/capabilities/remote", headers=headers,
            json={"kind": "mcp", "name": "remote", "endpoint": "https://example.org/mcp"},
        ).status_code, 200)
        self.assertEqual(self.client.put(
            "/api/admin/agents/default/capabilities/remote", headers=headers,
            json={"assigned": True},
        ).status_code, 422)
        visible = self.client.get(
            "/api/agents/default/capabilities", headers={"X-Session-Token": alice}
        )
        self.assertEqual(visible.status_code, 200)
        self.assertEqual(
            {item["kind"] for item in visible.json()["capabilities"]}, {"prompt", "skill"}
        )
        self.assertEqual(visible.json()["agent"]["agent_id"], "default")
        self.assertTrue(all("content" in item and "endpoint" not in item
                            for item in visible.json()["capabilities"]))
        fake = self.fake_harness()
        with patch("app.web.create_harness", return_value=fake) as create:
            response = self.post_chat(alice, "你好")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("使用简洁语言", fake.run.call_args.args[0])
        patch_path = Path(create.call_args.args[0].patches[-1])
        self.assertTrue(patch_path.exists())
        self.assertIn("dsh-tool-skill", patch_path.read_text(encoding="utf-8"))


    def test_workflow_runs_steps_and_keeps_records_private(self) -> None:
        alice = self.register_and_enable("alice")
        bob = self.register_and_enable("bob")
        headers = {"X-Session-Token": alice}
        self.assertEqual(self.client.get("/api/engines").status_code, 401)
        catalog = self.client.get("/api/engines", headers=headers)
        self.assertEqual(catalog.status_code, 200)
        self.assertTrue(catalog.json()["engines"][0]["available"])
        created = self.client.post(
            "/api/workflows", headers=headers,
            json={"name": "Two steps", "engine_id": "dsh-0.1.5rc1", "steps": [
                {"kind": "agent", "name": "First", "agent_id": "default",
                 "instruction": "Read {{input}}"},
                {"kind": "agent", "name": "Second", "agent_id": "default",
                 "instruction": "Use {{previous}}"},
            ]},
        )
        self.assertEqual(created.status_code, 201, created.text)
        workflow_id = created.json()["workflow_id"]
        self.assertEqual(self.client.get("/api/workflows", headers={"X-Session-Token": bob})
                         .json()["workflows"], [])
        self.assertEqual(self.client.delete(
            f"/api/workflows/{workflow_id}", headers={"X-Session-Token": bob}
        ).status_code, 404)
        with patch("app.workflow_runner._run_agent", side_effect=["alpha", "finished"]) as agent_run:
            run = self.client.post(
                f"/api/workflows/{workflow_id}/runs", headers=headers,
                json={"input": "source", "provider": "deepseek-official",
                      "model": "test-model", "api_key": "user-test-key"},
            )
        self.assertEqual(run.status_code, 200, run.text)
        self.assertEqual(run.json()["status"], "completed")
        self.assertEqual(run.json()["output"], "finished")
        self.assertIn("source", agent_run.call_args_list[0].args[3])
        self.assertIn("alpha", agent_run.call_args_list[1].args[3])
        self.assertEqual(len(run.json()["steps"]), 2)
        run_id = run.json()["run_id"]
        self.assertEqual(self.client.get(
            f"/api/workflow-runs/{run_id}", headers={"X-Session-Token": bob}
        ).status_code, 404)
        self.assertEqual(len(self.client.get(
            f"/api/workflows/{workflow_id}/runs", headers=headers
        ).json()["runs"]), 1)

    def test_workflow_rejects_unassigned_mcp_and_uninstalled_plugin(self) -> None:
        alice = self.register_and_enable("alice")
        headers = {"X-Session-Token": alice}
        for step in (
            {"kind": "mcp_tool", "name": "Search", "agent_id": "default",
             "capability_id": "private", "tool_name": "search", "arguments": {}},
            {"kind": "plugin_tool", "name": "Export", "agent_id": "default",
             "tool_name": "unknown_tool"},
        ):
            result = self.client.post(
                "/api/workflows", headers=headers,
                json={"name": "Denied", "engine_id": "dsh-0.1.5rc1", "steps": [step]},
            )
            self.assertEqual(result.status_code, 403, result.text)

    def test_mcp_only_workflow_runs_without_model_key(self) -> None:
        alice = self.register_and_enable("alice")
        admin = self.login("admin", "admin-token")
        headers = {"X-Session-Token": alice}
        capability = "/api/my/capabilities/calculator"
        self.assertEqual(self.client.put(
            capability, headers=headers,
            json={"kind": "mcp", "name": "Calculator",
                  "endpoint": "https://example.com/mcp"},
        ).status_code, 200)
        self.assertEqual(self.client.put(
            "/api/my/agents/default/capabilities/calculator", headers=headers,
            json={"assigned": True},
        ).status_code, 200)
        self.assertEqual(self.client.put(
            "/api/admin/users/alice/mcps/calculator/approval",
            headers={"X-Session-Token": admin}, json={"approved": True},
        ).status_code, 200)
        visible = self.client.get(
            "/api/agents/default/capabilities", headers=headers,
        ).json()["capabilities"]
        self.assertEqual(len(visible), 1)
        assigned_id = visible[0]["capability_id"]
        created = self.client.post(
            "/api/workflows", headers=headers,
            json={"name": "Calculator", "engine_id": "dsh-0.1.5rc1", "steps": [{
                "kind": "mcp_tool", "name": "Add", "agent_id": "default",
                "capability_id": assigned_id, "tool_name": "add_numbers",
                "arguments": {"a": "{{input}}", "b": 3},
            }]},
        )
        self.assertEqual(created.status_code, 201, created.text)
        with patch("app.workflow_runner._call_mcp", return_value='{"result": 5}') as tool:
            run = self.client.post(
                f"/api/workflows/{created.json()['workflow_id']}/runs", headers=headers,
                json={"input": "2", "provider": "", "model": ""},
            )
        self.assertEqual(run.status_code, 200, run.text)
        self.assertEqual(run.json()["status"], "completed")
        self.assertEqual(run.json()["output"], '{"result": 5}')
        self.assertEqual(tool.call_args.args[1:], ("add_numbers", {"a": "2", "b": 3}))

    def test_chat_session_keeps_its_engine_version(self) -> None:
        alice = self.register_and_enable("alice")
        second = Engine(
            "dsh-other", "DSH other", "0.2.0rc2", "sdk-minimal",
            "D:/dsh-other/dsh.exe", True, (), True, "已安装",
        )
        with patch("app.web.create_harness", return_value=self.fake_harness()):
            first = self.post_chat(alice, "hello")
            self.assertEqual(first.status_code, 200, first.text)
            session_id = first.json()["session_id"]
        with patch("app.web.get_engine", return_value=second), patch(
            "app.web.create_harness", return_value=self.fake_harness()
        ):
            denied = self.post_chat(
                alice, "continue", session_id, engine_id="dsh-other"
            )
            fresh = self.post_chat(alice, "new", engine_id="dsh-other")
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(fresh.status_code, 200, fresh.text)
        self.assertEqual(fresh.json()["engine_id"], "dsh-other")

    def test_plugin_step_requires_a_successful_tool_call(self) -> None:
        fake = self.fake_harness("tool result")
        wrapper = MagicMock()
        wrapper.__enter__.return_value = fake
        step = {"agent_id": "default", "instruction": "", "tool_name": "demo_tool"}
        principal = Principal("alice", "user")
        with patch("app.workflow_runner.get_agent", return_value={"instructions": ""}), patch(
            "app.workflow_runner.create_harness", return_value=wrapper
        ):
            with self.assertRaisesRegex(RuntimeError, "没有成功执行"):
                _run_agent(
                    self.config, principal, step, "run", provider="deepseek-official",
                    model="test-model", api_key="test-key", plugin_tool="demo_tool",
                )
            fake.run.return_value.events = [
                {"type": "tool/call", "data": {"callId": "c1", "name": "demo_tool"}},
                {"type": "tool/result", "data": {
                    "message": {"toolCallId": "c1", "isError": False},
                }},
            ]
            self.assertEqual(_run_agent(
                self.config, principal, step, "run", provider="deepseek-official",
                model="test-model", api_key="test-key", plugin_tool="demo_tool",
            ), "tool result")


if __name__ == "__main__":
    unittest.main()
