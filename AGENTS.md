# Codex Rate 项目规则

通用协作规则沿用上级工作区 AGENTS.md；当前状态见 PROJECT.md。

- 目标：Windows 上只读的 Codex 桌面悬浮状态条。
- 入口：`run.py`；核心包：`codex_rate/`；回归：`python -m unittest discover -s tests -v`。
- Python 侧仅使用标准库；当前页识别 helper 使用 Windows 自带 .NET Framework／UI Automation。Python 打包依赖仅装入项目 `.venv`。
- 不修改 Codex 安装、配置、认证或会话文件，不代理模型请求。
- 日志只提取数值、计时和会话身份；不得把真实对话正文或原始日志写入仓库。
- 新旧 token 事件不能叠加；缺失计时、部分恢复和取消不能伪装成完整 TPS。
- 只在独立项目目录写入，不创建项目级 `.codex`。
- 验证分开报告：指标回归、本机日志、真实 GUI、打包程序；模拟数据不等于本机验收。
