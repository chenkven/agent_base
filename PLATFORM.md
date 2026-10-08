# 模型、Agent 与能力中心

本页描述网页服务的配置。首次安装由 `scripts/setup_mysql.py` 创建全部表；已有数据库请在 DBeaver 管理员连接中执行 [`mysql/migrate_platform.sql`](mysql/migrate_platform.sql)。普通应用账号只有增删改查权限。迁移后重启 FastAPI，用 `GET /ready` 检查数据库表。

## 管理顺序

1. 管理员登录，打开侧边栏的**管理工作台**。工作台按功能分为用户管理、Agent 授权、模型目录、Agent 管理、Prompt、Skill、MCP 和能力分配。
2. 在**模型目录**中新增或停用模型，并设置普通用户是否可用。模型 ID 必须是所选厂家实际支持的 ID；目录只管授权，不会替厂家验证购买资格。普通用户仍要填自己的 API Key。
3. 在 **Agent 管理**中建立 Agent，例如 `reviewer` 和 `lead`。可把 `lead` 的协作 Agent 设为 `reviewer`。默认 `default` Agent 对所有已启用账号开放。
4. 在 **Agent 授权**中从下拉列表选择普通用户和 `lead`。没有授权时，普通用户既看不到也无法调用它；后端在调用模型前再次校验。
5. 分别在 **Prompt**、**Skill**、**MCP** 中建立能力，再在 **能力分配**中绑定给 Agent。能力授权随 Agent 授权生效；协作 Agent 的能力也会在协作步骤中生效。MCP 不能绑定到对所有用户开放的 `default` Agent；先建受限 Agent，再授权需要使用它的账号。

普通用户登录后可打开侧边栏的**我的能力中心**，分别创建自己的 Prompt、Skill、MCP，再在**绑定 Agent**中选择已获授权的 Agent。个人能力以账号隔离，不会出现在其他用户的能力中心；管理员公共能力仍由管理员管理。个人 Prompt/Skill 保存并绑定后即可加载。个人 MCP 保存后先显示“待审核”，管理员在**用户 MCP 审核**中查看地址并批准后才会连接；用户修改地址会撤销原批准。给已有 Agent 改能力后，下一轮会重新创建该账号的 DSH 实例。现有数据库需用管理员连接执行 [`mysql/migrate_user_capabilities.sql`](mysql/migrate_user_capabilities.sql)。

修改模型、Agent、能力或 Key 后，请新建会话。服务端记录会话原来的 Agent，禁止在旧会话中切换。

历史会话在同一个 DSH 运行进程内沿用原生会话。服务重启后，网页保留原会话 ID 和 MySQL 消息记录，为 DSH 创建新的运行会话，并回放最近已完成的用户/助手文字对话。这样可以继续提问，但不会恢复之前的工具状态，且受上下文长度限制。这是网页服务的续聊适配，不是 DSH SDK 的原生会话恢复。

## 页面演示

管理员登录聊天页，点 **模型设置**选择 **能力演示 Agent**，再点 **配置与轨迹**查看 Agent 指令、已绑定 Prompt 的完整规则、可用 Skill，以及 MCP 服务。发送消息后，“MCP 服务与工具”会显示 DSH 本轮实际注册的工具；“本轮调用”只显示 DSH `tool/call` 和 `tool/result` 事件确认的调用，未调用时明确显示“模型直接回答”。这两处不能把“已配置”误认为“已调用”。普通用户需要管理员先在 **Agent 授权**中分配 `demo_agent`。

网页工作台参考 [DSH 开源 Web 布局](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-layout/README.md)的侧边导航、对话主体和按需打开的右侧面板。页面是本项目的 FastAPI 前端，底层运行仍由官方 DSH Python SDK 负责；它不等同于直接部署 DSH 自带的 Web App。手机端把历史会话、模型设置和配置轨迹折叠为按需打开的面板。

演示配置可在本机 MySQL 建表后运行 `\.venv\Scripts\python.exe scripts\seed_capability_demo.py` 创建。它给 `demo_agent` 绑定 `demo_prompt`、`demo-skill` 和 `demo_tools`。后者连接本机 FastAPI 托管的只读 MCP 服务 `http://127.0.0.1:8000/internal/mcp`，提供 `current_time` 和 `add_numbers`。可用下面的命令先验证协议，再在聊天框输入“请调用 MCP 的 add_numbers 工具计算 2 加 3”：

```powershell
.\.venv\Scripts\python.exe scripts\probe_demo_mcp.py
```

Skill ID 必须使用 DSH 接受的小写 kebab-case，例如 `review-skill`。在聊天框输入“请调用 skill 工具加载 demo-skill，然后核对这段信息”，右侧才会记录实际加载；只在面板中看到 Skill 名称表示它可用，不表示模型已经调用。

## 执行过程

`app/permissions.py` 验证登录和会话归属，`app/platform.py` 读取 MySQL 中的模型、Agent 与能力授权，`app/web.py` 执行检查并安排调用，`app/extensions.py` 为该 Agent 生成独立的 DSH 补丁，`app/agent.py` 创建官方 SDK 实例。

Prompt 能力和 Agent 指令会加入提交给模型的消息。它们目前是应用层的提示文本，**不是 DSH 的 system role**。Skill 能力写入当前用户和 Agent 的独立目录，通过 DSH 的 `dsh-skill`、`dsh-skill-filesystem` 与 `dsh-tool-skill` 插件加载；禁用默认技能目录，避免把主机或其他用户的 Skill 暴露给网页会话。MCP 能力用 DSH 的 `dsh-mcp-client` 连接管理员配置的 Streamable HTTP 服务。项目内置的只读演示服务由 `app/demo_mcp.py` 随 FastAPI 启动；外部 MCP 服务仍需自行运行且能从 FastAPI 主机访问，管理页面暂不支持填写 MCP 鉴权头。配置无效或服务不可达可能导致 Agent 启动失败，也可能让 Agent 启动但缺少该服务的工具；需要用实际工具调用验收。MCP 工具可能执行外部操作，管理员应仅向合适的 Agent 分配可信服务。

当主 Agent 设置了协作 Agent，网页服务先启动一个独立的 DSH Harness 运行协作任务，再把结果交给主 Agent 汇总。这个流程最多一层协作、每轮两次模型调用，共用用户所选厂家、模型、Key 与总超时。它是**基于两个 DSH 实例的应用层编排**，尚未启用 DSH 原生 subagent 服务。普通用户不能直接调用未获授权的协作 Agent；管理员授权主 Agent 即表示允许它调用配置的协作 Agent。

网页 DSH profile 固定为 `sdk-minimal`，`app/web_chat.patch.yml` 关闭 shell。模型目录和 Agent 授权由网页服务在调用前强制执行；DSH 插件工具权限仍由所加载的插件本身决定。DSH 的 [Python SDK 指南](https://deepseek-harness.github.io/deepseek-harness/en/guide/python-sdk)、[Skill 参考](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/skills)和 [MCP 参考](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/mcp)解释底层插件机制。

## 检查

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_web tests.test_extensions tests.test_trace -v
```

网页测试使用独立的 `agent_base_test` 数据库和模拟模型回复；Skill 测试会启动固定版本的 DSH 运行时，但不发送模型请求。完整 `unittest discover` 还会运行一次真实 API 冒烟测试并产生少量费用。`probe_demo_mcp.py` 验证演示 MCP 连接和工具结果；`probe_live_web.py --agent demo_agent` 会发送真实模型请求并打印实际注册与调用的工具，产生少量费用。
