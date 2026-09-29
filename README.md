# DeepSeek Harness Agent 底座

这是一个方便复用的 Python Agent 项目，命令行和网页服务都调用[DeepSeek Harness 官方 Python SDK](https://deepseek-harness.github.io/deepseek-harness/en/guide/python-sdk)。命令行使用 `sdk` profile；网页演示使用独立的 `sdk-minimal` profile，并关闭 shell 工具。

## 给导师使用的网页服务

本机启动（PowerShell，当前位置为项目根目录）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

先在本机 `.env` 中设置 `DEEPSEEK_API_KEY` 和自己生成的 `SERVICE_ACCESS_TOKEN`。可以用下面的命令生成访问口令，复制结果填入 `.env`；不要把真实口令提交到代码仓库。

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

然后启动服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.web:app --host 127.0.0.1 --port 8000
```

在本机浏览器打开 <http://127.0.0.1:8000/>，输入访问口令即可聊天。`/health` 返回 `{"status":"ok"}` 只表示网页服务已启动；能否聊天还取决于 Key 和服务器到 DeepSeek 的网络连接。`127.0.0.1` 仅供本机访问，不能作为给导师的公网地址。

### 部署到 Render，取得公网地址

仓库已提供 `render.yaml` 和 `.python-version`。需要你自己的 GitHub 账号和 Render 账号：

1. 当前项目的远程仓库在 Gitee。把项目同步到**你自己的** GitHub、GitLab 或 Bitbucket 仓库，供 Render 连接。确认 `.env`、`.venv`、`.harness` 等没有上传。
2. 在 [Render Dashboard](https://dashboard.render.com/) 选择 **New → Blueprint**，连接该仓库，使用仓库中的 `render.yaml`。
3. 按界面提示填写 `DEEPSEEK_API_KEY` 和 `SERVICE_ACCESS_TOKEN` 两个环境变量。访问口令可用上面的 Python 命令生成；只把口令发给导师，不要把 API Key 发给导师。
4. 等待部署成功，打开 Render 提供的 `https://...onrender.com/` 地址，输入访问口令发送一条消息。验证完成后，把这个网址和访问口令发给导师。

Render 免费服务闲置 15 分钟后会休眠，再次打开通常需要约一分钟唤醒；本地会话文件在休眠、重启和重新部署后会丢失，因此网页演示的长对话不能保证跨重启续接。网页入口一次只处理一个 Agent 请求。若需要持续在线和永久保存会话，需要升级托管方案并配置持久存储。

网页服务代码在 `app/web.py`，页面在 `app/static/index.html`，网页专用的 Harness 配置在 `app/web_chat.patch.yml`。网页使用 `workspace-web/` 和 `.harness-web/`，与命令行数据隔离。要添加 RAG 等服务能力，可在 `app/web.py` 的调用流程中接入检索，或谨慎调整网页专用 profile；命令行的插件仍在 `config/*.patch.yml` 配置。

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
