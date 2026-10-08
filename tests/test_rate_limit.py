"""Shared login limiter behavior when the migration is pending or MySQL fails."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException
import mysql.connector

from app.rate_limit import SharedLoginRateLimiter


class SharedLoginRateLimiterTest(unittest.TestCase):
    def test_missing_table_uses_local_limit(self) -> None:
        limiter = SharedLoginRateLimiter()
        missing = mysql.connector.ProgrammingError(errno=1146, msg="missing table")
        with patch("app.rate_limit._connect", side_effect=missing):
            for _ in range(5):
                limiter.check("127.0.0.1", "admin")
                limiter.failure("127.0.0.1", "admin")
            with self.assertRaises(HTTPException) as blocked:
                limiter.check("127.0.0.1", "admin")
            self.assertEqual(blocked.exception.status_code, 429)
            limiter.success("127.0.0.1", "admin")
            limiter.check("127.0.0.1", "admin")

    def test_database_error_fails_closed(self) -> None:
        limiter = SharedLoginRateLimiter()
        denied = mysql.connector.ProgrammingError(errno=1044, msg="access denied")
        with patch("app.rate_limit._connect", side_effect=denied):
            with self.assertRaises(HTTPException) as error:
                limiter.check("127.0.0.1", "admin")
            self.assertEqual(error.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
