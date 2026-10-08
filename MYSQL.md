# 用 DBeaver 查看项目账号

项目现在使用本机 MySQL 8。DBeaver 是连接和查看 MySQL 的客户端，不负责运行数据库服务。

## 一次性建库

在项目根目录的 `.env` 末尾临时添加 MySQL 管理员登录信息：

```dotenv
MYSQL_SETUP_USER=root
MYSQL_SETUP_PASSWORD=你本机的MySQL密码
```

不要把密码发到聊天里。然后在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe scripts\setup_mysql.py
```

脚本会创建 `agent_base` 业务库及 `agent_base_test` 测试库、账号、会话、消息、登录限流表、权限受限的 `agent_base_app` 数据库用户，并用 `SERVICE_ACCESS_TOKEN` 建立首个 `admin` 管理员。账号密码仅保存带盐的 scrypt 哈希。成功后脚本将业务库连接信息写回 `.env`，并删除临时 `MYSQL_SETUP_USER` / `MYSQL_SETUP_PASSWORD` 两行。

已安装旧版数据库时，临时填写同样的 `MYSQL_SETUP_USER` 和 `MYSQL_SETUP_PASSWORD`，运行 `.\.venv\Scripts\python.exe scripts\migrate_messages.py`。脚本只增加 `messages` 和 `login_attempts` 两张表，不清除现有账号或会话，成功后删除 `.env` 中的临时管理凭据。迁移完成前，聊天历史仍只在本机浏览器，登录限流只在单个网页进程内生效。

如果管理员账号只保存在 DBeaver，不想写入 `.env`，用该账号连接，在 SQL 编辑器打开并执行 [mysql/migrate_foundation.sql](mysql/migrate_foundation.sql)。脚本对业务库和独立测试库各增加两张表，使用 `CREATE TABLE IF NOT EXISTS`，可安全重跑。普通的 `agent_base_app` 账号没有建表权限，不能执行这一步。

已有数据库启用模型目录、Agent 与能力中心时，在 DBeaver 管理员连接中执行 [mysql/migrate_platform.sql](mysql/migrate_platform.sql)。它会为业务库和测试库添加模型、Agent、授权、会话绑定和能力表，并填充默认 Agent 与模型目录；保留现有账号和会话。完成后重启 FastAPI。`/ready` 会检查这些表是否就绪。

## DBeaver 连接

1. 在 DBeaver 选择 **新建连接 → MySQL**。若提示下载驱动，按界面安装。
2. 主机填 `127.0.0.1`，端口填 `3306`，数据库填 `agent_base`。
3. 用户名填 `.env` 中的 `MYSQL_USER`（默认 `agent_base_app`），密码填 `.env` 中的 `MYSQL_PASSWORD`。
4. 点击“测试连接”，再展开 `agent_base → Tables → accounts → 数据`。可看到 `admin` 的角色为 `admin`。`password_hash` 是哈希值，不能从中读出明文密码。

网页登录使用用户名 `admin` 和 `SERVICE_ACCESS_TOKEN` 的值作为密码。普通用户从登录页注册，再由管理员在“管理中心”中启用。不要直接在 DBeaver 中修改 `password_hash`；账号管理需要同时处理登录票据。

本机 MySQL 仅供本机 FastAPI 和 DBeaver 使用。Render 等远端服务不能用 `127.0.0.1` 连到这台电脑，需要另行配置可访问的 MySQL 主机。
# 个人能力中心升级

已有数据库要在 DBeaver 的管理员连接中执行 [`mysql/migrate_user_capabilities.sql`](mysql/migrate_user_capabilities.sql)。脚本给正式库和测试库各增加个人能力表与 Agent 绑定表，不会删除现有账号或聊天记录。执行后重启 FastAPI，再访问 `/ready`。

