"""Login failure limits shared through MySQL, with a local pre-migration fallback."""

from contextlib import closing
from hashlib import sha256
import secrets
from threading import Lock
from time import monotonic, time

from fastapi import HTTPException
import mysql.connector

from app.permissions import _connect


class LoginRateLimiter:
    def __init__(self, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._lock = Lock()
        self._attempts: dict[tuple[str, str], tuple[int, float, float]] = {}

    def check(self, ip: str, username: str) -> None:
        key = (ip, username.lower())
        now = monotonic()
        with self._lock:
            state = self._attempts.get(key)
            if state is None:
                return
            _, first_failure, locked_until = state
            if locked_until > now:
                raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")
            if now - first_failure >= self.window_seconds:
                self._attempts.pop(key, None)

    def failure(self, ip: str, username: str) -> None:
        key = (ip, username.lower())
        now = monotonic()
        with self._lock:
            if len(self._attempts) >= 10000:
                self._attempts = {
                    candidate: state for candidate, state in self._attempts.items()
                    if state[2] > now or now - state[1] < self.window_seconds
                }
                if len(self._attempts) >= 10000:
                    oldest = min(self._attempts, key=lambda candidate: self._attempts[candidate][1])
                    self._attempts.pop(oldest)
            count, first_failure, _ = self._attempts.get(key, (0, now, 0.0))
            if now - first_failure >= self.window_seconds:
                count, first_failure = 0, now
            count += 1
            locked_until = now + self.window_seconds if count >= self.max_failures else 0.0
            self._attempts[key] = (count, first_failure, locked_until)

    def success(self, ip: str, username: str) -> None:
        with self._lock:
            self._attempts.pop((ip, username.lower()), None)


class SharedLoginRateLimiter:
    """Use row locks so failed attempts count across workers after migration."""

    def __init__(self, max_failures: int = 5, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.fallback = LoginRateLimiter(max_failures, window_seconds)

    @staticmethod
    def _key(ip: str, username: str) -> str:
        return sha256(f"{ip}\0{username.lower()}".encode()).hexdigest()

    def check(self, ip: str, username: str) -> None:
        try:
            with closing(_connect()) as connection:
                row = connection.execute(
                    "SELECT first_failure, locked_until FROM login_attempts WHERE key_hash = ?",
                    (self._key(ip, username),),
                ).fetchone()
        except mysql.connector.Error as exc:
            if exc.errno != 1146:
                raise HTTPException(status_code=503, detail="登录保护服务暂不可用") from None
            return self.fallback.check(ip, username)
        if row and row[1] > int(time()):
            raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")

    def failure(self, ip: str, username: str) -> None:
        now = int(time())
        key = self._key(ip, username)
        try:
            with closing(_connect()) as connection:
                with connection:
                    connection.execute(
                        "INSERT IGNORE INTO login_attempts "
                        "(key_hash, failures, first_failure, locked_until) VALUES (?, 0, 0, 0)",
                        (key,),
                    )
                    row = connection.execute(
                        "SELECT failures, first_failure FROM login_attempts "
                        "WHERE key_hash = ? FOR UPDATE",
                        (key,),
                    ).fetchone()
                    count, first = row
                    if now - first >= self.window_seconds:
                        count, first = 0, now
                    count += 1
                    locked_until = now + self.window_seconds if count >= self.max_failures else 0
                    connection.execute(
                        "UPDATE login_attempts SET failures = ?, first_failure = ?, "
                        "locked_until = ? WHERE key_hash = ?",
                        (count, first, locked_until, key),
                    )
                    if secrets.randbelow(100) == 0:
                        connection.execute(
                            "DELETE FROM login_attempts WHERE first_failure < ? "
                            "AND locked_until < ? LIMIT 1000",
                            (now - self.window_seconds, now),
                        )
        except mysql.connector.Error as exc:
            if exc.errno != 1146:
                raise HTTPException(status_code=503, detail="登录保护服务暂不可用") from None
            self.fallback.failure(ip, username)

    def success(self, ip: str, username: str) -> None:
        try:
            with closing(_connect()) as connection:
                with connection:
                    connection.execute(
                        "DELETE FROM login_attempts WHERE key_hash = ?",
                        (self._key(ip, username),),
                    )
        except mysql.connector.Error as exc:
            if exc.errno != 1146:
                raise HTTPException(status_code=503, detail="登录保护服务暂不可用") from None
            self.fallback.success(ip, username)
