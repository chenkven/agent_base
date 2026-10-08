# 本机 FastAPI + 花生壳临时公网映射

在项目根目录打开两个 PowerShell 终端。先按 [MYSQL.md](MYSQL.md) 建库，并确认本机 MySQL 服务正在运行、`.env` 已配置 `DEEPSEEK_API_KEY`，不要把口令提交到仓库。

第一个终端启动服务，并保持终端运行。脚本会在进程意外退出后重启：

```powershell
.\scripts\run_web.ps1
```

若电脑必须通过 Windows 系统代理访问模型 API，先在同一个 PowerShell 终端执行以下命令，再运行上面的启动脚本。设置只对这个终端及其启动的服务进程生效，不修改项目或系统代理配置：

```powershell
$modelUri = [Uri]'https://api.deepseek.com'
$systemProxy = [System.Net.WebRequest]::GetSystemWebProxy().GetProxy($modelUri)
if ($systemProxy -eq $modelUri) { throw 'Windows 没有为 DeepSeek 配置系统代理' }
$env:HTTPS_PROXY = $systemProxy.AbsoluteUri
$env:HTTP_PROXY = $systemProxy.AbsoluteUri
$env:NODE_USE_ENV_PROXY = '1'
.\scripts\run_web.ps1
```

本机检查：打开 `http://127.0.0.1:8000/ready`，应返回 `{"status":"ready"}`；如返回 503，检查 MySQL。

第二个终端启动花生壳官方 CLI。首次使用时按浏览器提示登录并授权：

```powershell
npx.cmd -y @aweray/hsk-cli auth login --method loopback --format json
.\scripts\run_tunnel.ps1
```

CLI 输出的 `public_url` 是给导师的公网地址，脚本同时把最新地址写入 `.service-state/public_url.txt`。第二个终端也要保持运行；重连后要把新地址告诉导师。

此免费临时映射有到期时间；到期、关闭电脑或停止任一进程后，重新启动并把新的地址发给导师。导师可在登录页注册，管理员再启用该账号。不要把 `DEEPSEEK_API_KEY` 或管理员密码发给导师。

`/health` 只验证网页服务和公网映射。若聊天返回 502，还要检查本机到 `https://api.deepseek.com` 的连接；花生壳不会替本机连接模型 API。
