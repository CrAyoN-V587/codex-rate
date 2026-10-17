# 第三方组件和来源

本文列出 Codex Rate Windows 发布包中的运行时组件、许可文本及设计参考。运行时依赖与设计参考分别说明。

## 打包运行时

| 组件 | 来源及许可文本 |
| --- | --- |
| Python 3.12.7 与附带标准库 | [Python](https://www.python.org/)，完整运行时许可和附带第三方说明见 `licenses/Python-3.12.7-LICENSE.txt` |
| Tcl 8.6.13 | [Tcl](https://www.tcl-lang.org/)，见 `licenses/Tcl-8.6.13-LICENSE.txt` |
| Tk 8.6.13 | [Tk](https://www.tcl-lang.org/)，原始许可文本见 `licenses/Tk-8.6-LICENSE.txt` |
| PyInstaller 6.22.3 bootloader 与运行时 hooks | [PyInstaller](https://pyinstaller.org/)，GPL 及 bootloader exception、运行时 hooks 条款见 `licenses/PyInstaller-6.22.3-COPYING.txt` |
| OpenSSL 3.0.15 的 libcrypto | [OpenSSL](https://github.com/openssl/openssl/tree/openssl-3.0.15)，Apache 2.0 文本见 `licenses/OpenSSL-3.0.15-LICENSE.txt` |
| SQLite、zlib、libffi 等 Python 附带组件 | 按 Python Windows 运行时的附带许可说明分发；见完整 Python 许可文本 |

Microsoft C/C++ runtime DLL 随 Python Windows 运行时分发。Windows UI Automation 和 .NET Framework 由操作系统提供，其系统框架程序集不包含在发布包中。

许可文本保存在源代码仓库和便携 ZIP 的 `licenses/` 目录中，并嵌入单文件 EXE。便携包中的文本可直接阅读。

## 设计与技术资料参考

- [codex-statusbar](https://github.com/dongyue-19/codex-statusbar)：Windows 悬浮条形式、宿主身份识别和 IPC 协议调查。
- [CC Switch](https://github.com/farion1231/cc-switch)：输出速率和首 token 延迟的区分。
- [CodexBar](https://github.com/steipete/CodexBar)：整轮性能与 token 用量的指标口径。
- [Tokscale](https://github.com/junhoyeo/tokscale)：用量统计展示参考。

以上参考项目不作为本程序的依赖分发。Codex Rate 是非官方第三方工具，与 OpenAI 无隶属关系。第三方组件分别适用其许可；项目当前尚未为原创代码声明开源许可证。
