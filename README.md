# Codex Rate

Windows 上只读的 Codex 桌面悬浮状态条：**有效 TPS · 本轮输出 · 缓存命中率**。使用圆角、白底、黑字和约 3 像素黑色外轮廓，自动跟随左侧选中的本地对话，并支持当前用户登录自启动。

运行时不需要 API Key，不代理请求，不修改 Codex、认证、配置或会话文件。读取日志时只提取计数、计时和会话身份；不保存或展示对话正文。

## 使用

从 [GitHub Releases](https://github.com/CrAyoN-V587/codex-rate/releases) 下载 Windows x64 便携 ZIP，解压后双击 `CodexRate.exe` 或 `Start-Codex-Rate.cmd`。也可直接下载单文件 EXE。无需另装 Python 或 .NET SDK。

从源码首次运行需要 Python 和 Tk，先编译当前页读取器并构建 EXE：

```powershell
.\build.cmd
python run.py
```

- 状态条跟随可见的 Codex 窗口；Codex 最小化或其他应用处于前台时隐藏，托盘仍可访问。
- **拖动**调整相对位置，位置会保存；**双击**查看指标定义和完整数字；**右键／⋮**打开菜单。
- 托盘图标左键打开详情，右键打开菜单；菜单可切主题、固定会话、选择最近会话、重置位置和退出。
- 默认根据左侧对话的“当前页面”标记自动切换。切换加载、页面尚未识别时三项均显示 `--`，不会沿用上一段对话的数字，也不会选取后台最近活动会话代替。
- `~` 表示本轮未结束，当前显示最近已完成响应边界的测量；不是每个 token 都实时更新。
- 未运行 Codex 时只保留托盘，不显示等待条、不启动会话读取器；检测到 Codex 窗口后自动响应。Codex 关闭后停止读取，回到后台等待。

## 开机自启动

三点菜单可选择“启用开机自启动”或“关闭开机自启动”。首次下载不会自动注册；更新同一路径下的 EXE 会沿用已有设置，不必重复注册。

自启动仅在当前用户登录时运行，使用 `HKCU/Software/Microsoft/Windows/CurrentVersion/Run` 下的 `CodexRate` 值，命令为带双引号的永久 EXE 路径加 `--background`。不需要管理员权限、不创建服务或计划任务。登录时静默保留托盘，Codex 窗口出现后自动显示。

```powershell
# 也可直接通过 EXE 管理
.\dist\CodexRate.exe --install-startup
.\dist\CodexRate.exe --uninstall-startup
```

“退出 Codex Rate”只退出本次运行；关闭自启动需用菜单或上面的卸载启动项参数。移动或删除 EXE 后，需重新启用自启动以更新路径。诊断时 `--background` 可直接验证后台启动方式；重复后台启动不会弹出已运行提示。

更多启动方式如下。界面参数也可传给 EXE；JSON 快照使用源码命令：

```powershell
# 独立窗口，方便看清布局；仍读取真实数据
python run.py --preview

# 可选：手动固定会话；右键菜单可恢复自动跟随
python run.py --thread YOUR-CONVERSATION-UUID

# 只读 JSON 快照，适合排障
python run.py --snapshot --thread YOUR-CONVERSATION-UUID

# 明确标注“演示”的合成界面，不产生模型请求
python run.py --demo --preview
```

默认读取 `CODEX_HOME`；未设置时读取用户主目录下的 `.codex`。`--home` 可指定其他 Codex home。主题与位置保存在 `%LOCALAPPDATA%/CodexRate/settings.json`；可退出后删除此文件来重置。手动固定只在本次运行有效。

## 指标合同

| 指标 | 定义 |
| --- | --- |
| 本轮输出 | 官方 `output_tokens`，含推理 token，也含生成工具参数的 token。不是屏幕可见文字量。 |
| 缓存命中率 | 本轮 `cached_input_tokens / input_tokens`。缓存是输入的子集，不额外相加。零输入显示 `--`。 |
| 有效 TPS | 本轮输出 token ÷ 从 `task_started` 到最近已完成响应的有效耗时。 |

有效耗时先取该时间窗口，再扣除已记录的工具**独占**时间。工具区间先取并集；工具与明确模型活动重叠的部分保留。首 token 等待、队列延迟和日志记录延迟包含在内，因此**不是服务端纯解码 TPS**。本轮结束后保留最终值。

只用 Reasoning／AgentMessage 的时间作分母会遗漏部分工具参数的生成耗时，本机已观测到这种情况，所以首版使用统一的有效 TPS 口径，不混用两种速度。

- 新格式以 `token_usage_record` 的 `response_id` 去重，不叠加滞后的旧 `token_count`。
- 本轮官方累计值与响应总和核对；旧格式把整个 thread 累计值复制到 `turn_token_usage` 的情况不直接采信。
- 首次只读取日志末尾 4 MiB，之后增量读取。缺失本轮开头时 TPS 为 `--`；输出／缓存仅在有可信本轮累计值时显示。
- 取消、用量矛盾、无有效时间或小于 0.5 秒的时间窗口不显示 TPS。
- 半行留待后续写完；坏行使当前轮不可用，下一完整轮可以恢复。

## 范围和限制

- 首版支持 Windows 10/11 x64、本地 Codex MSIX 包 `OpenAI.Codex_*`；当前实际运行验证为 Windows 11＋Codex 26.1013.4894.0。
- 悬浮位置以宿主窗口底部偏移定位，可拖动调整；未使用输入框 UI Automation 锚点，无法保证不同布局自动贴合工具栏。
- 当前页识别只读取 Windows UI Automation 的 `current=page` 导航名称，并在本地 `threads.name` 中精确、唯一匹配；不使用原始首条提示词作为显示名称。匹配不唯一、侧栏没有可见选中项或读取中断时显示 `--`。
- **多个 Codex 窗口、远程会话、普通 ChatGPT 聊天不在本版验收范围。** 无障碍名称不是 UUID，远程或其他页面若与某一本地会话完全同名，无法仅凭此接口严格区分。仅验收左侧切换本地对话的行为。
- IPC 跟随集合不再充当当前页来源；自动跟随也不再回退为“最近”活动。
- 日志中未提供的逐 token 时间无法恢复，不伪造实时流速。计时受客户端负载、日志延迟和系统时钟变化影响。
- 负坐标通过原生 `SetWindowPos` 处理；尚未进行真实双屏／不同 DPI 显示器之间的拖动实测。

## 开发与构建

实际工具链：Python 3.12.7、Tk 8.6、PyInstaller 6.22.3。考虑过 Python 3.14，但本机已有的 3.12 已满足标准库需求，首版没有安装新的语言运行时。

v0.3.1 发布验证：70 条回归、编译和独立审阅通过；便携 ZIP 从带空格路径启动后读取真实指标，退出无残留。此前真实左侧 A→B→A 切换、三点菜单主题与退出也已验证。真实 Windows 重启／重登录和双屏／混合 DPI 尚未实测。

```powershell
python -m unittest discover -s tests -v
python -m compileall -q codex_rate run.py
.\build.cmd
```

Python 运行时没有第三方依赖。当前页面读取器使用 Windows 自带的 .NET Framework 4.x／UI Automation，不需要 .NET SDK；`build.cmd` 会先编译 `native/ActiveConversation.cs`，再将它打入单文件 EXE。源码启动自动跟随前也需要先构建这个 helper。`build.cmd` 仅在项目 `.venv` 安装 Python 打包依赖。

创建便携发布包：`python package_release.py`。打包时保留 `licenses/` 与 `THIRD_PARTY_NOTICES.md`；具体分发内容和验证边界见 `RELEASE_NOTES.md`。

构建输出到 `dist/`，中间文件在 `build/`。这三个目录都不提交 Git；退出程序后可手动删除来清理。

源码职责：`metrics.py` 计量、`reader.py` 增量读日志、`active.py`／`native/ActiveConversation.cs` 当前对话识别、`ipc.py` 跟随流元数据、`windows.py` Win32／托盘、`app.py` 界面与生命周期。

## 参考

- [codex-statusbar](https://github.com/dongyue-19/codex-statusbar)：悬浮条形式、Windows 宿主身份和 IPC 协议调查。
- [CC Switch](https://github.com/farion1231/cc-switch)：区分首 token 延迟与输出吞吐的展示方式。
- [CodexBar](https://github.com/steipete/CodexBar)：本轮性能与用量的口径区分。
- [Tokscale](https://github.com/junhoyeo/tokscale)：模型／日期维度统计的参考。

本项目为独立实现，未打包或执行上述参考项目的代码。运行时来源与许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。当前未为原创代码另行声明开源许可证。
