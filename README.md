# DeepSeek Harness Agent 底座

这是一个基于 [DeepSeek Harness Python SDK](https://deepseek-harness.github.io/deepseek-harness/en/guide/python-sdk) 的可复用 Agent 项目。它提供命令行入口和 FastAPI 网页：DSH 负责模型与工具调用，本项目负责账号权限、模型目录、能力配置、会话管理和工作流编排。网页使用独立的 `sdk-minimal` profile，并关闭 shell 工具。

## 当前能力

| 模块 | 实现方式 |
| --- | --- |
| 账号与权限 | MySQL 保存账号和登录会话。用户注册后由管理员启用；服务端校验模型、Agent、能力及会话归属。 |
| 模型 | 可配置 DeepSeek、千问（百炼北京地域）、OpenAI、Anthropic、Kimi 和智谱 GLM 的模型目录。普通用户填写所选厂家的个人 API Key。 |
| 能力中心 | 管理员配置公共 Prompt、Skill、MCP；用户管理自己的能力，并绑定到有权使用的 Agent。个人 MCP 地址需管理员审核。 |
| 多 Agent | 主 Agent 可配置一个协作 Agent。网页先运行协作任务，再把结果交给主 Agent 汇总。 |
| DSH 引擎 | 聊天及工作流可选择已登记且已安装的 DSH；每个会话固定使用创建时的引擎。 |
| 工作流 | 每人可保存自己的步骤列表，顺序执行 Agent、MCP 工具或已登记的 DSH 插件工具，并查看每步记录。 |
| 历史会话 | 消息保存在 MySQL；服务重启后可用最近已完成的文字对话重建上下文并继续聊天。 |

**当前只配置了 `deepseek-harness-sdk==0.1.5rc1`。**引擎管理页展示已登记版本及状态，不在网页中安装 DSH。多 Agent 协作和步骤列表工作流由本项目编排，目前不是 DSH 原生 subagent 或原生 Workflow。Prompt 与 Agent 规则由应用层加入模型输入；Skill、MCP 通过 DSH 补丁加载。实现边界见 [模型、Agent 与能力中心](PLATFORM.md)和 [引擎与工作流](ENGINE_WORKFLOW.md)。

## 本地运行

项目使用 Python 3.12（见 `.python-version`）和 MySQL 8。在 Windows PowerShell 中进入项目根目录：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中设置 `SERVICE_ACCESS_TOKEN`，用于空数据库首次创建 `admin` 管理员。命令行或网页管理员需要使用服务器 DeepSeek Key 时，再设置 `DEEPSEEK_API_KEY`。普通网页用户在会话页填写自己的模型 Key；项目不会把它保存到 MySQL。`.env` 已被 Git 忽略。管理员初始口令可用下面的命令生成：

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

全新安装时，先启动本机 MySQL，在 `.env` 中临时填写 `MYSQL_SETUP_USER`、`MYSQL_SETUP_PASSWORD`（MySQL 管理员凭据），运行：

```powershell
.\.venv\Scripts\python.exe scripts\setup_mysql.py
```

脚本创建 `agent_base` 业务库、`agent_base_test` 测试库及受限的应用账号，并将应用连接信息写入 `.env`。已有旧库应由 MySQL 管理员按需执行 `mysql/` 中的迁移脚本：`migrate_foundation.sql`、`migrate_platform.sql`、`migrate_user_capabilities.sql`、`migrate_engines_workflows.sql`。建库、DBeaver 连接和迁移细节见 [MYSQL.md](MYSQL.md)。

启动网页：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.web:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000/>，用 `admin` 和首次配置的 `SERVICE_ACCESS_TOKEN` 登录。`/ready` 返回 `{"status":"ready"}` 表示服务及所需数据库表就绪；`/health` 只检查网页进程。

## 页面使用

1. **账号：**用户在登录页注册；管理员在“管理工作台 → 用户管理”启用账号。角色和登录校验见 [PERMISSIONS.md](PERMISSIONS.md)。
2. **聊天：**在“模型设置”中选择 Agent、DSH 引擎、厂家和模型，填入对应 API Key。管理员选择 DeepSeek 时可使用服务器 Key。切换 Agent、引擎、厂家、模型或 Key 后先点“新会话”；旧会话仍在历史列表。
3. **能力：**在“我的能力中心”建立个人 Prompt、Skill、MCP，并绑定到可用 Agent。管理员可维护公共能力和授权。聊天页“配置与轨迹”区分已配置的能力与本轮实际调用的工具。可运行 `\.venv\Scripts\python.exe scripts\seed_capability_demo.py` 创建演示 Agent。
4. **工作流：**打开 `/workflows`，添加最多 8 个步骤并保存。`{{input}}`、`{{previous}}`、`{{step1}}` 等占位符可传递结果。仅含 MCP 工具的工作流无需模型 Key；包含 Agent 或插件步骤时需要可用模型和 Key。每步运行前重新检查授权，运行记录只对创建者可见。
5. **引擎：**管理员打开 `/engines` 查看版本状态。新增版本需先独立安装，再由服务器管理员编辑 [`config/engines.json`](config/engines.json) 登记可执行文件；首次真实调用还需验证与当前 SDK 的协议兼容性。

当前引擎目录没有登记插件工具。工作流的插件步骤须先在对应 DSH profile 安装插件，再登记工具名；运行时会检查 DSH 轨迹，确认指定工具确实成功调用。MCP 步骤直接调用已授权服务中的指定工具。配置方法见 [ENGINE_WORKFLOW.md](ENGINE_WORKFLOW.md)。

历史会话保存用户和助手消息。服务重启后，网页用最近已完成的文字对话重建上下文；较早的消息仍可查看，但之前的工具运行状态不会恢复。API Key 不写入历史，刷新或续接旧会话时需重新填写。

## 命令行

命令行使用 `sdk` profile 和 `.env` 的 `DEEPSEEK_API_KEY`，与网页的数据目录隔离：

```powershell
.\.venv\Scripts\python.exe main.py doctor
.\.venv\Scripts\python.exe main.py run "请介绍一下你能做什么"
.\.venv\Scripts\python.exe main.py chat
```

`doctor` 只检查本地配置，不调用模型。`run` 执行一次任务；`chat` 连续对话，输入 `exit` 退出。`run` 和 `chat` 可传 `--session-id` 沿用已有会话。真实模型调用可能产生费用。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

网页测试使用并清理**独立测试库**，不要把 `MYSQL_TEST_DATABASE` 指向业务库。完整测试包含真实 DeepSeek API 冒烟测试：配置 `DEEPSEEK_API_KEY` 后会调用模型并可能产生费用；未配置时该项跳过。只运行网页接口测试可执行 `\.venv\Scripts\python.exe -m unittest tests.test_web -v`。

## 代码结构

| 路径 | 职责 |
| --- | --- |
| `main.py`、`app/cli.py` | `doctor`、单次任务和连续命令行对话。 |
| `app/web.py`、`app/static/` | FastAPI 接口，以及登录、聊天、引擎和工作流页面。 |
| `app/permissions.py`、`app/platform.py`、`app/user_capabilities.py` | 账号、模型、Agent、公共及个人能力授权。 |
| `app/engines.py`、`config/engines.json` | DSH 引擎目录、可用性检查及会话版本绑定。 |
| `app/workflows.py`、`app/workflow_runner.py` | 工作流定义、步骤校验、执行及运行记录。 |
| `app/extensions.py`、`app/agent.py` | 生成 DSH 能力补丁并创建 SDK 实例。 |
| `mysql/`、`scripts/`、`tests/` | 数据库脚本、演示与维护脚本、自动测试。 |

网页工作区和 DSH 数据分别位于 `workspace-web/`、`.harness-web/`；命令行使用 `workspace/`、`.harness/`。这些运行目录和 `.env` 均被 Git 忽略。扩展补丁的格式与位置见 [config/README.md](config/README.md)。

## 如何扩展

- **新增 Agent：**在管理工作台创建 Agent、设置规则或协作 Agent，再给用户授权；调用入口和权限校验分别在 `app/web.py`、`app/platform.py`。
- **新增 Prompt、Skill、MCP：**通过公共或个人能力中心创建并绑定 Agent。新增 MCP 服务须提供可从服务端访问的 Streamable HTTP 地址，个人地址还需管理员审核。
- **新增模型：**现有厂家可在“模型目录”登记实际支持的模型 ID；接入新厂家还需更新 `app/platform.py` 的厂家允许列表、`app/agent.py` 的 Key 传递、`app/web_providers.patch.yml` 和页面选项，并验证 SDK 适配。
- **新增 DSH 版本或插件：**在服务器安装对应运行时或插件，再更新 `config/engines.json`。插件工具需要真实调用验收，登记名称不会自动安装插件。
- **新增工作流步骤类型：**在 `app/workflows.py` 增加定义与授权校验，在 `app/workflow_runner.py` 增加执行逻辑，并同步更新 `app/static/workflows.js` 的编辑表单。
