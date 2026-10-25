# Codex Rate

Codex Rate 是面向 Windows Codex 桌面客户端的本地监测工具，通过悬浮状态条显示**有效 TPS、本轮输出 Token 和缓存命中率**，并跟随左侧选中的本地对话切换。

本项目为独立维护的第三方工具，非 OpenAI 官方产品，与 OpenAI 无隶属关系。

[下载预发布版本](https://github.com/CrAyoN-V587/codex-rate/releases) · [版本说明](RELEASE_NOTES.md) · [Windows 11 兼容性](https://github.com/CrAyoN-V587/codex-rate/blob/main/docs/windows11-compatibility.md)

## 功能

- **对话跟随**：识别当前选中的本地对话，切换加载期间显示 `--`。
- **指标展示**：显示任务吞吐、输出 Token 及输入缓存命中率；双击查看完整数值和计算说明。
- **活动与恢复**：标示最近的工具调用、子代理调度和等待响应活动；识别程序异常后自动重试，详情解释数据不可用原因。
- **检测时间**：第二行小字显示“上次检测：x秒之前”，按最近有效计量记录计算；切换或无数据时显示 `--`。
- **窗口交互**：支持拖动定位、明暗主题、手动固定会话和托盘操作。
- **后台等待**：Codex 未运行时保留托盘；检测到窗口后显示状态条。
- **登录自启动**：可选的当前用户启动项，无需管理员权限。

## 快速开始

### 运行要求

| 项目 | 要求 |
| --- | --- |
| 目标平台 | Windows 11 x64，Intel／AMD 处理器 |
| Codex 客户端 | 本地 MSIX 安装的 Windows 客户端，包身份为 `OpenAI.Codex_*` |
| 系统组件 | .NET Framework 4.x 和 Windows UI Automation |
| Python／.NET SDK | 运行发布包不需要；EXE 已内置 Python、Tk 和当前页识别程序 |

已验证环境包括 Windows 11 build 26200 x64 与 Codex 26.1013.4894.0、26.1016.8622.0。其他系统版本、安装方式和架构的状态见[兼容性说明](https://github.com/CrAyoN-V587/codex-rate/blob/main/docs/windows11-compatibility.md)。

### 下载与启动

1. 从 [GitHub Releases](https://github.com/CrAyoN-V587/codex-rate/releases) 下载 Windows x64 便携 ZIP，或单文件 `CodexRate.exe`。
2. 将文件放入固定目录。使用 ZIP 时，先完整解压。
3. 双击 `CodexRate.exe`；便携包也可通过 `Start-Codex-Rate.cmd` 启动。
4. 打开 Codex 并选中一个本地对话，等待指标加载。

Codex 未打开时，程序在托盘等待。Codex 最小化或其他应用处于前台时，状态条通常隐藏；菜单、详情或拖动操作期间保持可见。Codex 关闭后，程序停止会话读取并返回等待状态。

### 常用操作

| 操作 | 结果 |
| --- | --- |
| 拖动状态条 | 调整相对位置并保存 |
| 双击状态条 | 打开指标详情 |
| 右键或点击 `⋮` | 打开菜单，切换主题、固定会话、重置位置或退出 |
| 托盘图标左键 | 打开详情 |
| 托盘图标右键 | 打开菜单 |

手动固定会话仅对本次运行有效，可在菜单中恢复自动跟随。

## 登录自启动

在菜单中选择“启用开机自启动”后，程序会在当前 Windows 用户登录时后台运行。首次下载不会自动注册启动项。

启动项使用 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下的 `CodexRate` 值，指向当前 EXE 的固定路径并附加 `--background` 参数。它不创建系统服务或计划任务。

也可在 EXE 所在目录执行：

```powershell
.\CodexRate.exe --install-startup
.\CodexRate.exe --uninstall-startup
```

“退出 Codex Rate”只结束本次运行。要取消后续登录启动，请使用“关闭开机自启动”或上述卸载启动项命令。移动 EXE 后，需要重新启用自启动以更新路径。

## 指标说明

本轮统计以 Codex 日志中的任务轮次为单位，一轮可能包含多次模型响应和工具调用。

| 指标 | 计算口径 |
| --- | --- |
| 有效 TPS | 本轮已记录的输出 Token 总量 ÷ 有效耗时，单位为 `tok/s` |
| 本轮输出 | Codex 会话日志记录的 `output_tokens`，包含推理输出和工具参数 |
| 缓存命中率 | 本轮 `cached_input_tokens / input_tokens`；缓存属于输入的子集 |

有效耗时从本轮开始计至最近一次已完成的模型响应，再扣除日志记录的工具独占时间。重叠工具区间按并集计算；工具与明确模型活动重叠的部分保留。

该指标反映客户端观测到的任务吞吐，包含首 Token 等待、排队和日志记录延迟，**不等同于服务端纯解码速度**。数据在模型响应完成后更新，不按单个 Token 实时刷新。

- `~` 表示本轮仍在进行，显示的是最近一次已完成响应后的测量值。
- 状态条中的“工具”“代理”“等待”表示主会话日志中最近观测到的活动。工具和代理调用期间保留本轮最近一次可信测量；尚无计量记录时显示 `--`。这些标记不表示子代理的实时运行状态。
- `--` 表示该项指标无法计算或尚未就绪。切换对话、无法识别选中页或加载数据时，三项指标均显示 `--`。
- 缺失本轮起点、任务取消、计时不足 0.5 秒或数据不一致时，不显示有效 TPS。
- 缺失本轮起点时，输出量和缓存比例仅在存在可信本轮累计值时显示。

读取器优先处理新格式 `token_usage_record`，按响应 ID 去重；旧格式 `token_count` 用于兼容读取，不与新格式叠加。启动时分块向前查找本轮起点，最多回溯 64 MiB，再分块恢复本轮记录。恢复期间显示 `--`，完成后增量更新；达到上限仍缺少起点时，不计算 TPS。

已确认类型的超大非计量内容记录会被跳过，工具输出或上下文压缩内容不会仅因超过 8 MiB 就使计量失效。未完成的行等待后续写入；损坏或无法安全识别的超大记录仍使当前轮数据不可用，下一完整轮可恢复。详情可查看恢复状态、读取积压和跳过数量。

三项数值仅统计当前会话。派发子代理不会清空主会话计量，也不会将子代理输出混入主会话。父子会话汇总属于[后续优化方向](https://github.com/CrAyoN-V587/codex-rate/blob/main/docs/roadmap.md)。

## 数据与配置

程序读取本地会话元数据、Token 计数和时间信息，不持久化或展示对话正文，不向外部服务发送会话数据。程序不要求 API Key，不代理模型请求，不修改 Codex 的安装文件、认证、配置或会话日志。

| 配置 | 位置或行为 |
| --- | --- |
| Codex 数据目录 | 优先使用 `--home`，其次为 `CODEX_HOME`，默认是用户主目录下的 `.codex` |
| 状态条设置 | `%LOCALAPPDATA%\CodexRate\settings.json`，保存主题和位置 |
| 登录启动项 | 当前用户的 HKCU Run 注册表项，仅在主动启用时写入 |

退出程序后删除状态条设置文件，可恢复默认主题和位置。该操作不影响 Codex 数据。

## 已知限制

- 自动跟随依赖可见导航项的名称与本地会话显示名称的唯一匹配。侧栏隐藏、名称重复、数据库结构变化或客户端界面改版可能导致识别失败。
- 远程会话、普通 ChatGPT 聊天和完整多窗口行为不在当前验证范围。其他页面与本地会话同名时，仅凭导航名称无法可靠区分。
- 状态条按窗口底部偏移定位，可手动调整；不同布局下可能无法自动贴合输入框工具栏。
- ARM64、各档缩放、混合 DPI、多显示器和真实 Windows 登录触发尚未完成运行验证。
- 发布的 EXE 未签名，不提供自动更新。下载或运行可能受到系统与组织应用策略限制。

详细环境条件和后续适配计划见 [Windows 11 兼容性说明](https://github.com/CrAyoN-V587/codex-rate/blob/main/docs/windows11-compatibility.md)。

## 开发与构建

已使用的构建环境：Python 3.12.7、Tk 8.6、PyInstaller 6.22.3，以及 Windows 自带的 .NET Framework C# 编译器。

在仓库根目录执行：

```powershell
# 测试与编译检查
python -m unittest discover -s tests -v
python -m compileall -q codex_rate run.py package_release.py

# 编译当前页识别程序并构建单文件 EXE
.\build.cmd

# 从源码运行；首次运行前需完成上述构建
python run.py

# 基于已构建的 EXE 创建便携 ZIP
python package_release.py
```

Python 应用代码仅使用标准库。`build.cmd` 将 Python 打包依赖安装到项目 `.venv`，输出 EXE 至 `dist/`；中间文件保存在 `build/`。这些生成目录不纳入版本控制。

源码运行时可使用以下参数：

```powershell
python run.py --preview                         # 独立窗口，读取真实数据
python run.py --demo --preview                  # 标有“演示”的合成数据
python run.py --thread YOUR-CONVERSATION-UUID    # 固定会话
python run.py --snapshot --thread YOUR-CONVERSATION-UUID
```

`--snapshot` 输出 JSON，建议通过源码命令使用；无控制台的发布 EXE 不适合作为终端输出入口。`--home` 可指定 Codex 数据目录，`--settings` 可指定状态条设置文件。

## 验证状态

v0.3.2 已通过 97 条自动化测试、Python 编译检查和独立代码审查。新增覆盖超大工具输出、长轮恢复、恢复上限、跨块半行、页面识别程序重启与关闭竞态，以及工具期间保留三项数值和检测时间刷新。自动化测试包含对系统接口的模拟。

本次运行验证包括真实长轮恢复与完整扫描一致、真实识别程序退出后恢复，以及真实管道卡住后的超时重启。此前已有本地对话 A→B→A 切换、菜单主题切换与退出、便携包及真实会话读取记录。完整记录见 [PROJECT.md](https://github.com/CrAyoN-V587/codex-rate/blob/main/PROJECT.md)；这些结果不替代其他电脑、真实登录和多屏环境的验证。

## 设计参考与许可

设计与技术资料参考了 [codex-statusbar](https://github.com/dongyue-19/codex-statusbar)、[CC Switch](https://github.com/farion1231/cc-switch)、[CodexBar](https://github.com/steipete/CodexBar) 和 [Tokscale](https://github.com/junhoyeo/tokscale)。它们不作为本项目的程序依赖分发。

打包运行时的来源和许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与 [licenses/](licenses/)。项目当前尚未为原创代码声明开源许可证。
