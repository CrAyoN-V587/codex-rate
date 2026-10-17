# Windows 11 兼容性说明

评估日期：2026-10-17；对象：v0.3.1 Windows x64 发布包。

## 结论

当前发布包面向 Intel／AMD 的 Windows 11 x64。Python、Tk 和当前页识别程序随 EXE 提供，设置与登录启动项按当前用户保存。

已完成运行验证的组合为 Windows 11 build 26200 x64 与 Codex 26.1013.4894.0。本文记录 v0.3.1 的实现条件、现有证据和后续验证计划；其他组合尚待验证。

## 条件与证据

| 项目 | 当前状态 | 其他电脑上的条件／边界 |
| --- | --- | --- |
| CPU 架构 | EXE 的 PE machine 为 `0x8664`，即 x64 | Intel／AMD x64 是当前目标；没有原生 ARM64 包或 ARM 实机验收 |
| Python、Tk | EXE 内置运行时和许可 | 用户无需安装 Python；尚未在没有 Python 的全新 Windows 虚拟机单独验收 |
| .NET Framework | 当前页识别程序使用系统的 4.x Framework／UI Automation，不需要 SDK | Windows 11 常规安装已包含 Framework；经过裁剪或企业定制的系统需确认组件可用 |
| Codex 安装 | Python 与 C# 均按 `OpenAI.Codex_*` MSIX 包身份识别 | MSIX 安装的 Windows 客户端为当前识别范围；解压版、其他包名或未来安装方式未确认 |
| Codex 数据 | 默认当前用户 `.codex`，支持 `CODEX_HOME`／`--home` | 非默认数据目录需传给本程序；自启动后的环境也应能定位该目录 |
| 当前对话识别 | 读取可见 `current=page` 导航名称，匹配本地显示名称 | 同名、侧栏隐藏、不同 Codex 数据结构或界面改版可能使自动跟随显示 `--` |
| 权限 | 当前用户普通权限路径已运行；不要求管理员 | 两个程序均按普通用户运行；跨用户或跨权限级别没有验收 |
| 路径 | 带空格的便携解压路径已实测；启动命令正确加引号 | 中文路径有模拟测试，尚无全新中文 Windows 用户目录实测 |
| 屏幕缩放 | 初始化时请求 Per-Monitor V2，并使用原生屏幕坐标 | 尚未逐档验证 100／125／150／200%；固定像素间距与字体仍需跨缩放验证 |
| 多显示器 | 已避免用 Tk 负坐标语法定位窗口 | 左侧副屏、热插拔、主屏切换及混合 DPI 尚未实测；旧偏移可能不再合适，可重置位置 |
| 登录自启动 | HKCU Run 的命令注册及读回已验证 | 需用户自行启用；真实 Windows 重启／重登录触发尚未实测；移动 EXE 后需重新注册 |
| 下载与运行策略 | 当前 EXE 未签名 | SmartScreen 或企业应用策略可能影响运行；项目不要求关闭系统安全功能 |

Windows 11 原始版本预装 .NET Framework 4.8，较新版本预装 4.8.1，常规系统通常已具备所需运行时。依赖可用性与应用运行验证分别记录。[Microsoft 版本与依赖表](https://learn.microsoft.com/en-us/dotnet/framework/install/versions-and-dependencies)

Windows 11 on Arm 提供 x64 仿真。本项目尚未在 ARM 设备上验证 Tk、UIA 识别程序与 Codex 客户端的组合，也未提供原生 ARM64 包。[Microsoft Arm 仿真说明](https://learn.microsoft.com/en-us/windows/arm/apps-on-arm-x86-emulation)

Windows UI Automation 受进程权限与 UIAccess 条件约束，跨权限访问不在当前支持范围。[Microsoft UI Automation 权限说明](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview)

## 后续适配优先级

1. **环境诊断。** 输出 Windows build、架构、Framework 状态、Codex 包身份、数据目录及必要数据库字段是否存在，辅助定位识别失败原因。诊断默认不包含对话标题、正文、认证或原始日志。
2. **缩放与位置处理。** 检查 DPI 设置结果，按宿主显示器 DPI 调整布局，在显示器变化后重新校正位置，并进行真实双屏验证。
3. **完善 Codex 版本失配提示。** 区分找不到 Codex、找不到数据、数据库字段变化和 UIA 无法识别，保留 `--`，不猜测另一段对话。
4. **架构与安装方式。** 在具备对应测试环境后，评估 ARM64 与其他 Codex 安装方式，并分别记录构建与运行结果。

## 最小跨机验收

在一台独立的 Windows 11 x64 电脑上，以普通用户运行便携包，依次验证启动与退出、本地对话 A→B→A 切换、加载期 `--`、菜单与拖动、Codex 关闭后的等待与重新识别，以及登录自启动的启用和禁用。随后在第二种缩放比例和双屏环境复测。

问题记录应包含系统与 Codex 版本、架构、缩放、安装方式和数据目录类型；无需提供会话正文或认证文件。
