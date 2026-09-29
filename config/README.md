# Harness 扩展配置

此目录放可选的 `*.patch.yml` 文件。启动时，`app/config.py` 会按文件名顺序把它们传给官方 SDK 的 `patches` 参数；默认没有补丁。

Harness 的插件用 JavaScript/TypeScript 编写，插件安装、配置格式和工具注册请参考[官方开发文档](https://deepseek-harness.github.io/deepseek-harness/en/develop/basic/)。先让基础项目跑通，再按需要加入插件。
