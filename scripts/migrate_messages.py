"""Add the history and shared login-limit tables to existing MySQL databases."""

import os
from pathlib import Path
import re

from dotenv import load_dotenv, unset_key
import mysql.connector


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
SCHEMA_FILE = ROOT / "mysql" / "schema.sql"
IDENTIFIER = re.compile(r"^[a-zA-Z0-9_]+$")


def main() -> None:
    load_dotenv(ENV_FILE, override=True)
    setup_user = os.getenv("MYSQL_SETUP_USER", "").strip()
    setup_password = os.getenv("MYSQL_SETUP_PASSWORD", "")
    if not setup_user or not setup_password:
        raise SystemExit("缺少 MYSQL_SETUP_USER / MYSQL_SETUP_PASSWORD；现有账号数据未改动")
    database = os.getenv("MYSQL_DATABASE", "agent_base").strip()
    test_database = os.getenv("MYSQL_TEST_DATABASE", "agent_base_test").strip()
    if not all(IDENTIFIER.fullmatch(name) for name in (database, test_database)):
        raise SystemExit("数据库名无效")
    if test_database == database or not test_database.endswith("_test"):
        raise SystemExit("测试库必须是不同且以 _test 结尾的数据库")
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    statements = []
    for table in ("messages", "login_attempts"):
        match = re.search(
            rf"CREATE TABLE IF NOT EXISTS {table}\s*\(.*?\) ENGINE=InnoDB;", schema, re.S
        )
        if match is None:
            raise SystemExit(f"未在 mysql/schema.sql 找到 {table} 表定义")
        statements.append(match.group())

    connection = mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=setup_user,
        password=setup_password,
        connection_timeout=5,
    )
    try:
        cursor = connection.cursor()
        try:
            for name in (database, test_database):
                cursor.execute(f"USE `{name}`")
                for statement in statements:
                    cursor.execute(statement)
            connection.commit()
        finally:
            cursor.close()
    finally:
        connection.close()
    unset_key(ENV_FILE, "MYSQL_SETUP_PASSWORD")
    unset_key(ENV_FILE, "MYSQL_SETUP_USER")
    print("消息及登录限流表已在业务库和测试库就绪；临时 MySQL 管理凭据已从 .env 移除。")


if __name__ == "__main__":
    main()
