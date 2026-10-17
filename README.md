# Codex Rate

Windows 上只读的 Codex 桌面悬浮状态条：**有效 TPS · 本轮输出 · 缓存命中率**。

运行时不需要 API Key，不代理请求，不修改 Codex、认证、配置或会话文件。读取日志时只提取计数、计时和会话身份；不保存或展示对话正文。不默认注册开机自启。

## 使用

双击 `Start-Codex-Rate.cmd`，或直接运行 `dist/CodexRate.exe`。EXE 自带 Python／Tk 运行时，无需另装 Python。源码运行需要 Python 和 Tk：

```powershell
python run.py
```

- 状态条跟随可见的 Codex 窗口；Codex 最小化或其他应用处于前台时隐藏，托盘仍可访问。
- **拖动**调整相对位置，位置会保存；**双击**查看指标定义和完整数字；**右键／⋮**打开菜单。
- 托盘图标左键打开详情，右键打开菜单；菜单可切主题、固定会话、选择最近会话、重置位置和退出。
- 标注 **“最近”** 时表示最近活动模式：IPC 缺失或同时跟随多个会话，不能确定当前标签。它不保证对应屏幕上打开的聊天。
- `~` 表示本轮未结束，当前显示最近已完成响应边界的测量；不是每个 token 都实时更新。
- 未运行 Codex 时保留一个等待条，可通过右键或托盘退出。

更多启动方式如下。界面参数也可传给 EXE；JSON 快照使用源码命令：

```powershell
# 独立窗口，方便看清布局；仍读取真实数据
python run.py --preview

# 固定会话，排除多个跟随流的歧义
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
- IPC 是内部协议。单个跟随会话时使用它；多个跟随流时显示“最近”活动，不把广播顺序当作当前标签。
- **多个 Codex 窗口、远程会话、普通 ChatGPT 聊天不在首版验收范围。** 远程 IPC 目标显示不可用，不冒用同 ID 的本地日志。
- 日志中未提供的逐 token 时间无法恢复，不伪造实时流速。计时受客户端负载、日志延迟和系统时钟变化影响。
- 负坐标通过原生 `SetWindowPos` 处理；尚未进行真实双屏／不同 DPI 显示器之间的拖动实测。

## 开发与构建

实际工具链：Python 3.12.7、Tk 8.6、PyInstaller 6.22.3。考虑过 Python 3.14，但本机已有的 3.12 已满足标准库需求，首版没有安装新的语言运行时。

```powershell
python -m unittest discover -s tests -v
python -m compileall -q codex_rate run.py
.\build.cmd
```

运行时没有第三方依赖；`build.cmd` 仅在项目 `.venv` 安装打包依赖。构建输出到 `dist/`，中间文件在 `build/`。这三个目录都不提交 Git；退出程序后可手动删除来清理。

源码职责：`metrics.py` 计量、`reader.py` 增量读日志、`ipc.py` 会话跟随、`windows.py` Win32／托盘、`app.py` 界面与生命周期。

## 参考

- [codex-statusbar](https://github.com/dongyue-19/codex-statusbar)：悬浮条形式、Windows 宿主身份和 IPC 协议调查。
- [CC Switch](https://github.com/farion1231/cc-switch)：区分首 token 延迟与输出吞吐的展示方式。
- [CodexBar](https://github.com/steipete/CodexBar)：本轮性能与用量的口径区分。
- [Tokscale](https://github.com/junhoyeo/tokscale)：模型／日期维度统计的参考。

本项目为独立的 Python 实现；未打包或执行上述项目的代码，也未集成它们的运行时。当前为本地个人项目，未公开发布。
