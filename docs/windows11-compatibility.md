# Windows 11 兼容性评估

评估日期：2026-10-17；对象：v0.3.1 Windows x64 发布包。

## 结论

当前包适合在 Intel／AMD 的 Windows 11 x64 上试用：不依赖开发者的个人目录，Python／Tk 和辅助程序已经打包，自启动与设置按当前用户保存。但目前只有 Windows 11 build 26200 x64＋Codex 26.1013.4894.0 的真实运行证据，不能将其描述成所有 Windows 11 版本均已适配。

本轮完成的是发布可见性调整与兼容性评估；现有发布仍为 v0.3.1，尚未实施下表中的新功能。

## 条件与证据

| 项目 | 当前状态 | 其他电脑上的条件／边界 |
| --- | --- | --- |
| CPU 架构 | EXE 的 PE machine 为 `0x8664`，即 x64 | Intel／AMD x64 是当前目标；没有原生 ARM64 包或 ARM 实机验收 |
| Python、Tk | EXE 内置运行时和许可 | 用户无需安装 Python；尚未在没有 Python 的全新 Windows 虚拟机单独验收 |
| .NET Framework | helper 使用系统的 4.x Framework／UI Automation，不需要 SDK | Windows 11 常规安装已包含 Framework；经过裁剪或企业定制的系统需确认组件可用 |
| Codex 安装 | Python 与 C# 均按 `OpenAI.Codex_*` MSIX 包身份识别 | 商店／官方 MSIX 是当前识别范围；解压版、其他包名或未来安装方式未确认 |
| Codex 数据 | 默认当前用户 `.codex`，支持 `CODEX_HOME`／`--home` | 非默认数据目录需传给本程序；自启动后的环境也应能定位该目录 |
| 当前对话识别 | 读取可见 `current=page` 导航名称，匹配本地显示名称 | 同名、侧栏隐藏、不同 Codex 数据结构或界面改版可能使自动跟随显示 `--` |
| 权限 | 当前用户普通权限路径已运行；不要求管理员 | 两个程序均按普通用户运行；跨用户或跨权限级别没有验收 |
| 路径 | 带空格的便携解压路径已实测；启动命令正确加引号 | 中文路径有模拟测试，尚无全新中文 Windows 用户目录实测 |
| 屏幕缩放 | 代码尝试开启 Per-Monitor V2，并使用原生屏幕坐标 | 没有逐档验证 100／125／150／200%；固定像素间距与字体可能需要进一步处理 |
| 多显示器 | 已避免用 Tk 负坐标语法定位窗口 | 左侧副屏、热插拔、主屏切换及混合 DPI 尚未实测；旧偏移可能不再合适，可重置位置 |
| 登录自启动 | HKCU Run 的命令注册及读回已验证 | 需用户自行启用；真实 Windows 重启／重登录触发尚未实测；移动 EXE 后需重新注册 |
| 下载与运行策略 | 当前 EXE 未签名 | SmartScreen 或企业应用策略可能影响运行；项目不要求关闭系统安全功能 |

Microsoft 的版本表注明 Windows 11 原始版本预装 .NET Framework 4.8，较新版本预装 4.8.1。因此普通 Win11 的主要依赖通常已具备，但这不等于本项目已经在这些版本上实测。[Microsoft 版本与依赖表](https://learn.microsoft.com/en-us/dotnet/framework/install/versions-and-dependencies)

Windows 11 on Arm 提供 x64 仿真，但这只能说明操作系统存在该能力，不能证明本项目的 Tk、UIA helper 和 Codex 识别组合已通过 ARM 验收。[Microsoft Arm 仿真说明](https://learn.microsoft.com/en-us/windows/arm/apps-on-arm-x86-emulation)

Windows UI Automation 受进程权限与 UIAccess 条件约束；本项目不将跨权限访问作为支持场景。[Microsoft UI Automation 权限说明](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview)

## 后续适配优先级

1. **先补环境诊断。** 输出 Windows build、架构、Framework 状态、Codex 包身份、数据目录及必要数据库字段是否存在。默认不输出对话标题、正文、认证或原始日志，方便其他用户报告“无法识别”。
2. **再补缩放与位置处理。** 检查 DPI 设置是否成功，按宿主显示器 DPI 调整布局，显示器变化后重新校正位置；用真实双屏验证，而不是只验证坐标公式。
3. **完善 Codex 版本失配提示。** 区分找不到 Codex、找不到数据、数据库字段变化和 UIA 无法识别，保留 `--`，不猜测另一段对话。
4. **最后扩展架构／安装方式。** 有真实 ARM64 或其他安装方式的使用需求和测试设备后，再增加对应包；不把 x64 仿真当成原生 ARM64 支持。

## 最小跨机验收

先选择一台非开发机的 Windows 11 x64，以普通用户运行便携包，验证：启动／退出、左侧 A→B→A 切换、加载期 `--`、主题／菜单／拖动、Codex 关闭后等待及再次打开、启用／禁用登录自启动。再在第二种缩放和双屏场景复测。出现问题时记录版本、缩放、安装方式和数据位置，不上传会话或认证文件。
