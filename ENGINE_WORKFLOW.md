# DSH 引擎与工作流

## 页面

- `/app`：在“模型与密钥”中选择 DSH 引擎。新会话绑定该引擎；历史会话只能沿用原引擎。
- `/engines`：管理员查看服务器引擎目录、版本、状态与已登记插件工具。
- `/workflows`：每个用户保存自己的步骤列表，运行并查看每步记录。包含 Agent 或插件步骤时，普通用户需填写自己的模型 API Key；仅含 MCP 工具时无需模型 Key。

## 安装另一套 DSH

当前只配置了项目内置的 `deepseek-harness-sdk==0.1.5rc1`。不同版本应安装在独立目录。由服务器管理员在 `config/engines.json` 添加条目，例如：

```json
{
  "id": "dsh-0.2.0rc2",
  "name": "DSH 0.2.0rc2",
  "version": "0.2.0rc2",
  "profile": "sdk-minimal",
  "dsh_bin": "D:/dsh-runtimes/0.2.0rc2/dsh.exe",
  "enabled": true,
  "plugin_tools": ["my_tool"]
}
```

`dsh_bin` 必须指向服务器上真实存在、提供 SDK JSON-RPC profile 的 DSH 可执行文件。程序从服务器配置读取路径，不接受浏览器传入的程序路径。不同引擎使用不同的工作区和 Harness home。新版与当前 Python SDK 的协议兼容性要用一次真实会话验收；可执行文件存在仅表示可尝试启动，不表示已验证兼容。没有安装的版本不会出现在选择框。

网页使用 `sdk-minimal`，因此其他 DSH 安装中的插件不会自动出现。把兼容插件安装到对应版本的 profile，并在 `plugin_tools` 中登记允许编排的工具名。不同版本的插件依赖需要分别验证。`plugin_tool` 步骤通过该版本的 DSH Agent 调用指定工具，并检查 DSH 轨迹确有成功调用；它返回的是 Agent 对工具结果的回复。MCP 步骤直接调用已分配且已审核的 MCP 工具。

## 工作流步骤

- `agent`：运行选定 Agent，加载它已分配的 Prompt、Skill、MCP。可在本步指令中使用 `{{input}}`、`{{previous}}`、`{{step1}}` 等占位符。
- `mcp_tool`：从该 Agent 已授权的 MCP 中选择一个服务，填写工具名与 JSON 参数。执行前再次核验授权。
- `plugin_tool`：只可选择引擎目录中登记的插件工具；执行后检查实际工具调用轨迹。

每个工作流最多 8 步。运行记录保存步骤状态、输入、输出、耗时和错误；API Key 不进入工作流定义或运行记录。运行时对每步重新核验 Agent、MCP 和模型权限。

## 数据库

首次升级现有数据库时，在 DBeaver 的管理员连接执行 `mysql/migrate_engines_workflows.sql`。脚本给正式库和独立测试库增加 `session_engines`、`workflows`、`workflow_runs` 和 `workflow_step_runs`，可重复执行。全新数据库的表定义也已写入 `mysql/schema.sql`。
