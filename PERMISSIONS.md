# 网页账号与权限

网页账号保存在 MySQL 的 `agent_base.accounts` 表，可用 DBeaver 查看。登录页提供**登录**和**注册**两个入口；密码以随机盐和 scrypt 派生值保存，数据库里没有明文密码。登录票据有效期为 8 小时，退出、停用、删除账号或重置密码后失效。

访客注册时设置用户名和 6～128 位密码，账号默认为“待启用”。管理员登录后在主会话页点击“用户管理”，启用账号后新用户才能登录。管理员还可以停用、删除其他用户和重置密码。删除会立即撤销登录、从用户列表移除账号，并保留用户名占位，以免其他人注册同名账号后接触旧会话数据。

普通用户进入会话页后选择厂家、模型和该厂家的 API Key。当前网页支持 DeepSeek、千问（阿里云百炼·北京）、OpenAI、Anthropic、Kimi（月之暗面）和智谱 GLM；每个厂家提供多个可选模型，模型 ID 必须是该厂家实际提供且账号有权调用的 ID。千问目前使用北京地域百炼按量计费接口与 Key，不支持 Token Plan Key。后端为该用户创建独立的 Harness 实例，在同一会话的后续消息中复用，退出登录或服务关闭时结束实例；未提交 Key 时拒绝聊天，不回退使用服务器的 `DEEPSEEK_API_KEY`。更换厂家、模型或 Key 后需点击“新会话”。管理员选 DeepSeek 且不填 Key 时使用服务器配置的 Key；选择其他厂家时也须填写自己的 Key。本项目不会把用户提交的 Key 写入 MySQL 或浏览器会话记录，也不会主动记录 Key；刷新页面后需要重新填写。请通过 HTTPS 公网地址提交 Key。

## 首次创建管理员

第一次连接空的 MySQL 账号表时，服务会用 `.env` 中的 `SERVICE_ACCESS_TOKEN` 建立用户名为 `admin` 的管理员账号。普通用户从登录页自行注册。

初始化只执行一次。之后注册、启用、停用、删除和重置密码都直接写入 MySQL；确认管理员登录正常后，可从 `.env` 移除初始口令配置。接口统一使用用户名、密码登录取得会话票据，后续请求通过 `X-Session-Token` 传递票据。

新部署仍需在 `.env` 中至少设置一次 `SERVICE_ACCESS_TOKEN` 以建立首个管理员账号。MySQL 配置在 `.env` 的 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_DATABASE`、`MYSQL_USER`、`MYSQL_PASSWORD`。不要把 `.env` 或密码发给别人。给导师单独创建普通用户账号即可，勿共享管理员密码。

## 角色区别

模型目录、Agent 授权和能力中心的配置见 [PLATFORM.md](PLATFORM.md)。管理员可配置并使用所有启用的模型与 Agent；普通用户只能看到并调用目录中对普通用户开放的模型，以及已获授权的 Agent。服务端在每次聊天前重新检查，因此从页面上修改请求参数也不能绕过授权。

| 功能 | 普通用户 | 管理员 |
| --- | --- | --- |
| 登录后聊天、续接自己的会话 | 可以 | 可以 |
| 续接其他用户的会话 | 拒绝，403 | 拒绝，403 |
| 查看用户列表及会话数 | 拒绝，403 | 可以 |
| 在登录页注册普通账号（待启用） | 可以 | 可以 |
| 查看、启用、停用、删除其他账号及重置密码 | 拒绝，403 | 可以 |
| 停用或删除自己当前使用的管理员账号 | 不适用 | 拒绝，403 |

新用户在登录页自行注册，管理员在“用户管理”里审核并启用。忘记密码后由管理员重置，密码不会在页面再次显示。

同一 IP 和用户名连续输错密码 5 次后，登录会暂时锁定 5 分钟，锁定期间返回 429。安装 `login_attempts` 表后，失败次数保存在 MySQL，可由多个网页进程共享；尚未迁移的部署使用单进程内存限流。花生壳或其他反向代理下，服务看到的客户端 IP 可能是代理地址，因此多个访客可能共用该 IP 的限速配额。

## 与 DeepSeek Harness 的关系

`app/permissions.py` 连接 MySQL，在 `app/web.py` 调用 Harness **之前**校验登录、角色和会话归属。网页端使用独立的 `sdk-minimal` profile，`app/web_chat.patch.yml` 关闭持久化 shell，`app/web_providers.patch.yml` 挂载 Harness 的 pi-ai 多厂家适配器；管理员也不能从网页执行 shell。用户目录分别是 `workspace-web/<用户ID>` 和 `.harness-web/<用户ID>`。

聊天请求按用户加锁：同一个用户的 Harness 调用依次执行，不同用户可并行。同步的 MySQL 和 SDK 工作在线程中运行，避免占用 FastAPI 的事件循环。

Harness 的[权限预设](https://deepseek-harness.github.io/deepseek-harness/reference/subsystems/permission-presets)控制沙箱与审批，[工具执行前门禁示例](https://deepseek-harness.github.io/deepseek-harness/reference/cookbook/extension-cookbook)控制工具调用。它们与网页登录角色是不同层次的权限；本项目的 `sdk-minimal` 没有完整的权限预设交互。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_web -v
```

网页权限测试使用独立的 `agent_base_test` MySQL 数据库，不调用模型，覆盖账号初始化、数据库密码哈希、角色、注册待启用、管理员启用/停用/删除、重置密码、票据失效、会话归属、消息持久化和跨实例登录限流。
