# 后续优化方向

调研日期：2026-10-25。以下为建议，除注明 v0.3.2 的内容外，均未实现。

## 当前改进

v0.3.2 聚焦工具调用与代理协作期间的可用性：处理超大日志行、恢复长轮次记录、恢复意外停止的页面识别程序，并展示最近活动、计量时间和中文数据状态。活动标记来自主会话日志，不代表子代理的实时运行状态；子代理用量仍单独归属其会话。

## 优先级与参考

| 优先级 | 建议 | 参考功能 | 本项目的实现边界与验收 |
| --- | --- | --- | --- |
| P1 | 主代理与子代理明细 | [Tokscale](https://github.com/junhoyeo/tokscale#readme) 的跨会话去重、Muse Code 子会话扫描及父级汇总去重；[CC Switch](https://github.com/farion1231/cc-switch#readme) 的会话与工具步骤展示 | 根据明确的父子标识和轮次边界关联，排除继承历史。主、子 TPS 分开；可汇总输出量，但不将 TPS 相加。缺失子日志要显示缺失。上述参考不等于已解决 Codex Desktop 的父子计量。 |
| P1 | 环境诊断与版本失配提示 | [codex-statusbar](https://github.com/dongyue-19/codex-statusbar#readme) 的 debug 状态、读取偏移和未知事件计数；[CodexBar](https://github.com/steipete/CodexBar#readme) 的数据时效和来源展示 | 在已有中文原因基础上，增加可复制的脱敏诊断：系统架构、客户端版本、日志格式、恢复进度、识别程序重启次数。默认排除会话标题、正文、认证和个人路径。 |
| P1 | 输入框定位与跨屏缩放 | [codex-statusbar](https://github.com/dongyue-19/codex-statusbar#readme) 的 UIA 控件锚点和按宽度压缩显示 | 保留拖动能力，优先使用可靠的输入区锚点，失配时退回窗口偏移。验证 100/125/150/200% 缩放、双屏移动、侧栏收起和窄窗口。 |
| P2 | 最近轮次与模型对比 | [ccusage](https://github.com/ccusage/ccusage#readme) 的会话、日期、模型拆分和 JSON 导出；[CC Switch](https://github.com/farion1231/cc-switch#readme) 的本地用量趋势 | 先提供最近数轮的输出、有效耗时、工具独占耗时和缓存比例。缓存按输入量加权；不同模型、不同计量口径分别展示。 |
| P2 | 更稳定的当前页身份 | [codex-statusbar](https://github.com/dongyue-19/codex-statusbar#readme) 的 IPC 与窗口探测可作调查线索 | 等待可验证的页面 UUID 来源，再解决同名会话、多窗口及远程页面问题。IPC following 集合和最近活动不能代替用户当前选中页。 |

## 参考项目的适用范围

- **codex-statusbar** 的 Windows 悬浮交互最接近本项目，可参考工具期间保留最近可信测量的表现；其模型时间窗口 TPS 与本项目有效 TPS 定义不同。
- **CodexBar** 主要提供额度、重置时间、成本和历史视图，不能作为 Windows 逐 Token 流速的实现证据。
- **Tokscale、ccusage、CC Switch** 更适合借鉴日志兼容、会话组织、去重和历史统计。没有本地日志的远程任务不能凭空计入本地统计。

建议按“代理明细与诊断 → 跨屏适配 → 历史对比”的顺序推进，继续保留三项主要指标。具体兼容验证清单见 [Windows 11 兼容性说明](windows11-compatibility.md)。
