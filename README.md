# DeepSeek Harness Agent 底座

网页权限的配置与测试见 [PERMISSIONS.md](PERMISSIONS.md)；模型、Agent 和能力中心见 [PLATFORM.md](PLATFORM.md)；用 DBeaver 连接 MySQL 见 [MYSQL.md](MYSQL.md)；本机花生壳映射的启动方式见 [LOCAL_TUNNEL.md](LOCAL_TUNNEL.md)。

这是一个方便复用的 Python Agent 项目，命令行和网页服务都调用[DeepSeek Harness 官方 Python SDK](https://deepseek-harness.github.io/deepseek-harness/en/guide/python-sdk)。命令行使用 `sdk` profile；网页演示使用独立的 `sdk-minimal` profile，并关闭 shell 工具。网页支持选择已配置的 DSH 引擎，并提供逐步执行的工作流编排；安装新版本、插件兼容性及数据库迁移见 [DSH 引擎与工作流说明](ENGINE_WORKFLOW.md)。

## 给用户使用的网页服务

本机启动（PowerShell，当前位置为项目根目录）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

先在本机 `.env` 中设置供管理员默认聊天和命令行使用的 `DEEPSEEK_API_KEY`，以及自己生成的 `SERVICE_ACCESS_TOKEN`。普通网页用户登录后选择模型厂家、模型 ID，并填写该厂家的个人 API Key；他们的聊天请求不会使用服务器的 Key。可以用下面的命令生成管理员初始口令，复制结果填入 `.env`；不要把真实口令提交到代码仓库。

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

先按 [MYSQL.md](MYSQL.md) 在本机 MySQL 建库并配置 `.env`，然后启动服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.web:app --host 127.0.0.1 --port 8000
```

若浏览器能访问网站、但聊天提示模型连接失败，先检查本机到模型 API 的连接。此 Windows 电脑在启用系统代理时，需要让启动服务的 Node 子进程使用同一代理；经过验证的临时 PowerShell 启动命令见 [LOCAL_TUNNEL.md](LOCAL_TUNNEL.md)。项目不保存代理地址，也不改变系统代理设置。

在本机浏览器打开 <http://127.0.0.1:8000/>。首页提供登录和普通用户注册；新注册账号需要管理员启用后才能登录。管理员首次使用用户名 `admin` 和 `SERVICE_ACCESS_TOKEN` 作为密码登录，在侧边栏的“管理工作台”中分别管理用户、Agent 授权、模型、Agent、公共 Prompt/Skill/MCP 和能力分配。每个已启用用户都有“我的能力中心”，可创建自己的 Prompt、Skill、MCP 并绑定到自己可用的 Agent；个人 MCP 地址需管理员在“用户 MCP 审核”批准后才会连接。现有数据库须先执行 [个人能力迁移 SQL](mysql/migrate_user_capabilities.sql)。会话页点“模型设置”选择 Agent、模型厂家与模型，并填写该厂家的 API Key。聊天页支持 DeepSeek、千问（阿里云百炼·北京）、OpenAI、Anthropic、Kimi 和智谱 GLM；可选模型由 MySQL 模型目录控制，管理员可增减可用模型。千问使用北京地域百炼按量计费 API Key，当前不接入 Token Plan Key；其他地域的 Key 需要配置对应地域地址。管理员选 DeepSeek 时可留空 Key 使用服务器配置。切换厂家、模型、Agent 或 Key 后先点“新会话”。页面不保存密钥，刷新后需重填，服务端在登录期间暂存对应 Harness 实例并在退出后释放。`/health` 返回 `{"status":"ok"}` 只表示网页服务已启动；能否聊天还取决于对应厂家 Key、模型权限和网络连接。`127.0.0.1` 仅供本机访问，不能作为给用户的公网地址。

聊天页点“配置与轨迹”会打开 Agent 面板，显示规则、已分配 Skill、MCP 服务，以及 DSH 本轮实际注册和调用的工具。运行 `\.venv\Scripts\python.exe scripts\seed_capability_demo.py` 后，管理员可以选择“能力演示 Agent”体验 Prompt、Skill 和项目自带的只读 MCP 工具。具体提问与验收步骤见 [PLATFORM.md](PLATFORM.md)。

点击“新会话”后，旧对话仍在侧边栏的“历史会话”中。执行 [MYSQL.md](MYSQL.md) 的升级脚本后，新消息会保存到 MySQL，可跨浏览器和设备查看；升级前或数据库暂不可用时，页面会提示“历史仅保存在本机浏览器”，并继续使用本地缓存。升级前已有的本地历史不会自动上传。API Key 不保存在历史记录中，继续旧会话时需重新填写原厂家的 Key。服务重启后也可以打开服务端历史继续提问：服务会用最近已完成的文字对话重建上下文，最多回放最近 20 轮和约 2.4 万字符。更早的消息仍可查看，但不会全部送进模型；先前的工具运行状态不会恢复。只有本机缓存、没有服务端消息记录的旧会话无法跨重启续聊。

同一账号一次只处理一条聊天请求，整个网页服务最多同时运行 8 条聊天请求；多余请求会立即返回 429 或 503。Harness 启动与模型调用共享 180 秒超时，可通过 `WEB_CHAT_TIMEOUT_SECONDS` 调整。超时会关闭该账号的 Harness，建议开始新会话再试。

### 部署到 Render，取得公网地址

仓库已提供 `render.yaml` 和 `.python-version`。需要你自己的 GitHub 账号和 Render 账号：

1. 当前项目的远程仓库在 Gitee。把项目同步到**你自己的** GitHub、GitLab 或 Bitbucket 仓库，供 Render 连接。确认 `.env`、`.venv`、`.harness` 等没有上传。
2. 在 [Render Dashboard](https://dashboard.render.com/) 选择 **New → Blueprint**，连接该仓库，使用仓库中的 `render.yaml`。
3. 按界面提示填写 `DEEPSEEK_API_KEY` 和 `SERVICE_ACCESS_TOKEN` 两个环境变量。管理员初始密码可用上面的 Python 命令生成；不要把 API Key 或管理员密码发给用户。
4. 等待部署成功，打开 Render 提供的 `https://...onrender.com/` 地址，用用户名 `admin` 和管理员初始密码登录。用户可以从登录页注册普通账号；管理员在“用户管理”中启用后，再把网址交给用户。

Render 免费服务闲置后可能休眠，再次打开需要等待唤醒。MySQL 版本需要配置 Render 可以访问的 MySQL 主机；本机的 `127.0.0.1` 只适用于本机和花生壳方案。`/health` 检查网页进程，`/ready` 还会检查 MySQL；Render 使用 `/ready` 作为健康检查。

网页服务代码在 `app/web.py`，登录/注册页在 `app/static/login.html` 和 `app/static/login.js`，聊天及管理页在 `app/static/index.html` 和 `app/static/chat.js`，共享样式在 `app/static/site.css`，工作台样式在 `app/static/workbench.css`。`app/permissions.py` 管账号和会话；`app/platform.py` 管模型、Agent 与公共能力；`app/user_capabilities.py` 管每个账号自己的能力及 MCP 审核；`app/extensions.py` 生成每个账号和 Agent 的 DSH Skill/MCP 补丁；`app/agent.py` 创建 SDK 实例。`app/web_providers.patch.yml` 增加模型厂家，`app/web_chat.patch.yml` 关闭网页 shell。网页使用 `workspace-web/` 和 `.harness-web/`，与命令行数据隔离。命令行插件仍在 `config/*.patch.yml` 配置。

网页接口的本地自动测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest tests.test_web -v
```

## 目录关系

```text
agent_base/
├─ main.py             命令行入口
├─ app/
│  ├─ cli.py           doctor / run / chat 三个命令
│  ├─ config.py        读取 .env，定位工作目录与扩展配置
│  └─ agent.py         创建官方 DeepSeekHarness 实例
├─ config/             可选的官方 Harness 配置补丁
├─ workspace/          Agent 默认处理文件的地方
├─ .harness/           首次运行时产生的 profile、会话等数据（自动创建）
├─ .env.example        配置示例，不含真实密钥
└─ requirements.txt    Python 依赖
```

调用顺序：`main.py → app/cli.py → app/config.py → app/agent.py → DeepSeek Harness SDK → 模型/工具/会话`。

## 在 VS Code 中启动（Windows PowerShell）

要求 Python 3.10+、Git、Windows x64，以及可用的 DeepSeek API Key。当前文件夹已经建好 `.venv` 并安装依赖；你可直接从第 2 步开始。

1. 新机器首次安装：

   ```powershell
   cd D:\vscodeprojects\agent_base
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. 新建自己的配置文件并填写密钥：

   ```powershell
   Copy-Item .env.example .env
   ```

   打开 `.env`，把 `DEEPSEEK_API_KEY=` 后面填成你的真实密钥。若使用官方接口，删除或注释 `DEEPSEEK_BASE_URL`；仅使用兼容代理时才设置它。`.env` 已被 `.gitignore` 排除。

3. 检查安装：

   ```powershell
   .\.venv\Scripts\python.exe main.py doctor
   ```

4. 执行一个任务：

   ```powershell
   .\.venv\Scripts\python.exe main.py run "阅读 workspace 中的文件，告诉我它们的主要内容"
   ```

   连续对话：

   ```powershell
   .\.venv\Scripts\python.exe main.py chat
   ```

   程序会打印会话 ID。以后传入 `--session-id 这个ID` 可以延续该会话；不传则开启新会话。

## 运行真实 API 冒烟测试

在 `.env` 中填写 `DEEPSEEK_API_KEY` 后运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

测试会在 `workspace/` 中创建临时工作目录和独立的 Harness 数据目录，向模型发送一轮简短任务，检查会话 ID、完成状态和非空回复，结束后清理临时目录。这会产生一次 API 调用和相应费用。未配置 Key 时，测试会显示 `skipped`。

## 以后如何复用

- 把需要 Agent 处理的文件放入 `workspace/`。
- 在 `.env` 中改 `AGENT_MODEL`、`AGENT_MAX_TOKENS`。`sdk` 是官方完整 profile，优先保留。
- 在 `config/` 中加入官方格式的 `*.patch.yml`，用于增减插件或调整配置。请先读该目录说明和官方插件文档。
- 把你自己的业务流程写在 `app/` 新模块中，然后从 `cli.py` 调用；底层 Harness 初始化放在 `agent.py`。

## 注意

`doctor` 只检查配置，不发送 API 请求。`run` 和 `chat` 会调用 DeepSeek API，产生相应费用。官方 Harness 仍处于开发预览阶段；它的工具可能执行命令和修改文件。先在 `workspace/` 放练习文件，并审查其权限与扩展插件。工作目录是 Agent 的默认项目目录，不能当成操作系统级隔离边界。
