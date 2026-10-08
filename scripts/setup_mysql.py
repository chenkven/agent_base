"""One-time local MySQL setup. Reads a temporary admin login from ignored .env."""

import os
from pathlib import Path
import re
import secrets
import sys

from dotenv import load_dotenv, set_key, unset_key
import mysql.connector


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ENV_FILE = ROOT / ".env"
SCHEMA_FILE = ROOT / "mysql" / "schema.sql"
IDENTIFIER = re.compile(r"^[a-zA-Z0-9_]+$")


def main() -> None:
    load_dotenv(ENV_FILE, override=True)
    setup_user = os.getenv("MYSQL_SETUP_USER", "").strip()
    setup_password = os.getenv("MYSQL_SETUP_PASSWORD", "")
    if not setup_user or not setup_password or setup_password == "你的MySQL密码":
        raise SystemExit("请先在 .env 填写 MYSQL_SETUP_USER 和 MYSQL_SETUP_PASSWORD")

    database = os.getenv("MYSQL_DATABASE", "agent_base").strip()
    test_database = os.getenv("MYSQL_TEST_DATABASE", "agent_base_test").strip()
    app_user = os.getenv("MYSQL_USER", "agent_base_app").strip()
    host = os.getenv("MYSQL_HOST", "127.0.0.1").strip()
    port = int(os.getenv("MYSQL_PORT", "3306"))
    if (
        not IDENTIFIER.fullmatch(database)
        or not IDENTIFIER.fullmatch(app_user)
        or not IDENTIFIER.fullmatch(test_database)
        or not test_database.endswith("_test")
        or test_database == database
    ):
        raise SystemExit("数据库和用户名只能使用字母、数字及下划线；测试库名须以 _test 结尾")
    if host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("本机安装脚本只支持 127.0.0.1 或 localhost")

    app_password = os.getenv("MYSQL_PASSWORD", "") or secrets.token_urlsafe(36)
    raw = mysql.connector.connect(
        host=host, port=port, user=setup_user, password=setup_password,
        connection_timeout=5,
    )
    try:
        cursor = raw.cursor()
        try:
            schema = SCHEMA_FILE.read_text(encoding="utf-8")
            for db_name in (database, test_database):
                for statement in schema.replace("agent_base", db_name).split(";"):
                    if statement.strip():
                        cursor.execute(statement)
            for allowed_host in ("localhost", "127.0.0.1"):
                cursor.execute(
                    f"CREATE USER IF NOT EXISTS '{app_user}'@'{allowed_host}' IDENTIFIED BY %s",
                    (app_password,),
                )
                cursor.execute(
                    f"ALTER USER '{app_user}'@'{allowed_host}' IDENTIFIED BY %s",
                    (app_password,),
                )
                for db_name in (database, test_database):
                    cursor.execute(
                        f"GRANT SELECT, INSERT, UPDATE, DELETE ON `{db_name}`.* "
                        f"TO '{app_user}'@'{allowed_host}'"
                    )
            raw.commit()
        finally:
            cursor.close()
    finally:
        raw.close()

    for key, value in {
        "MYSQL_HOST": host,
        "MYSQL_PORT": str(port),
        "MYSQL_DATABASE": database,
        "MYSQL_TEST_DATABASE": test_database,
        "MYSQL_USER": app_user,
        "MYSQL_PASSWORD": app_password,
    }.items():
        set_key(ENV_FILE, key, value)
        os.environ[key] = value

    # Seed the first administrator from SERVICE_ACCESS_TOKEN.
    from app.permissions import authenticate, list_users

    admin_password = os.getenv("SERVICE_ACCESS_TOKEN", "").strip()
    if not admin_password:
        raise SystemExit("MySQL 已创建，但 .env 缺少 SERVICE_ACCESS_TOKEN，管理员未建立")
    admin = authenticate("admin", admin_password)
    accounts = [(item["user_id"], item["role"]) for item in list_users(admin)]
    unset_key(ENV_FILE, "MYSQL_SETUP_PASSWORD")
    unset_key(ENV_FILE, "MYSQL_SETUP_USER")
    print({"database": database, "accounts": accounts, "dbeaver_user": app_user})
    print("管理员用户名是 admin，密码仍是原 SERVICE_ACCESS_TOKEN；MySQL 连接密码保存在 .env 的 MYSQL_PASSWORD。")


if __name__ == "__main__":
    main()
