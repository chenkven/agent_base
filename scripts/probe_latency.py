"""Measure web entry requests without printing credentials or session tokens."""

import argparse
import os
from pathlib import Path
from time import perf_counter

import httpx
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    password = os.getenv("SERVICE_ACCESS_TOKEN", "")
    if not password:
        raise SystemExit("SERVICE_ACCESS_TOKEN is not configured")

    with httpx.Client(base_url=args.base, timeout=25, follow_redirects=True) as client:
        def timed(label: str, method: str, path: str, **kwargs) -> httpx.Response:
            started = perf_counter()
            response = client.request(method, path, **kwargs)
            print(f"{label:18} {response.status_code:3} {(perf_counter() - started):6.2f}s")
            return response

        timed("login page", "GET", "/")
        timed("chat page", "GET", "/app")
        timed("chat JavaScript", "GET", "/static/chat.js?v=platform-7")
        login = timed("login", "POST", "/api/login", json={
            "username": "admin", "password": password,
        })
        login.raise_for_status()
        assert login.json().get("bootstrap", {}).get("user", {}).get("user_id") == "admin"
        headers = {"X-Session-Token": login.json()["session_token"]}
        try:
            timed("bootstrap (new)", "GET", "/api/bootstrap", headers=headers)
            timed("account", "GET", "/api/me", headers=headers)
            timed("models", "GET", "/api/models", headers=headers)
            timed("agents", "GET", "/api/agents", headers=headers)
            timed("capabilities", "GET", "/api/agents/default/capabilities", headers=headers)
            timed("history", "GET", "/api/chats", headers=headers)
        finally:
            timed("logout", "POST", "/api/logout", headers=headers)


if __name__ == "__main__":
    main()
