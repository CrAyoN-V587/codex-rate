# 第三方组件和来源

Codex Rate 的 Windows EXE 使用 PyInstaller 打包。源代码的实现参考与运行时组件分开列示；没有将参考项目的源码打入程序。

## 打包运行时

| 组件 | 来源及许可文本 |
| --- | --- |
| Python 3.12.7 与附带标准库 | [Python](https://www.python.org/)，完整运行时许可和附带第三方说明见 `licenses/Python-3.12.7-LICENSE.txt` |
| Tcl 8.6.13 | [Tcl](https://www.tcl-lang.org/)，见 `licenses/Tcl-8.6.13-LICENSE.txt` |
| Tk 8.6.13 | [Tk](https://www.tcl-lang.org/)，使用已安装运行时的原始许可，见 `licenses/Tk-8.6-LICENSE.txt` |
| PyInstaller 6.22.3 bootloader 与运行时 hooks | [PyInstaller](https://pyinstaller.org/)，GPL 及 bootloader exception、运行时 hooks 条款见 `licenses/PyInstaller-6.22.3-COPYING.txt` |
| OpenSSL 3.0.15 的 libcrypto | [OpenSSL](https://github.com/openssl/openssl/tree/openssl-3.0.15)，Apache 2.0 文本见 `licenses/OpenSSL-3.0.15-LICENSE.txt` |
| SQLite、zlib、libffi 等 Python 附带组件 | 按 Python Windows 运行时的附带许可说明分发；见完整 Python 许可文本 |

Microsoft C/C++ runtime DLL 来自 Python Windows 运行时；Windows UI Automation 和 .NET Framework 由系统提供，不将这些系统框架程序集打入 EXE。程序使用其公开的 Windows API。

上述许可文件同时保留在源代码仓库、便携 ZIP，以及单文件 EXE 内的 `licenses/` 资源中。可通过便携包直接阅读。

## 实现参考

- [codex-statusbar](https://github.com/dongyue-19/codex-statusbar)：Windows 悬浮条形式、宿主身份识别和 IPC 协议调查。
- [CC Switch](https://github.com/farion1231/cc-switch)：输出速率和首 token 延迟的区分。
- [CodexBar](https://github.com/steipete/CodexBar)：整轮性能与 token 用量的指标口径。
- [Tokscale](https://github.com/junhoyeo/tokscale)：用量统计展示参考。

Codex Rate 为独立实现，不隶属 OpenAI。第三方组件的许可不替本项目原创代码设定许可证；仓库当前未另行授予原创代码的开源许可。
