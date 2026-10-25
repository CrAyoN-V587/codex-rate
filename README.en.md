# Codex Rate

[简体中文](README.md) | **English**

Codex Rate is a local monitoring tool for the Codex desktop client on Windows. Its floating status bar shows **effective TPS, output tokens for the current turn, and input cache hit rate**, and follows the local conversation selected in the sidebar.

This is an independently maintained, unofficial third-party tool with no affiliation with OpenAI.

[Download a prerelease](https://github.com/CrAyoN-V587/codex-rate/releases) · [Release notes (Chinese)](RELEASE_NOTES.md) · [Windows 11 compatibility (Chinese)](https://github.com/CrAyoN-V587/codex-rate/blob/main/docs/windows11-compatibility.md)

Current application version: **v0.3.3 (prerelease)**. This README is available in Chinese and English; the application interface is currently in Chinese.

## Features

- **Conversation following**: Detects the selected local conversation and displays `--` while loading after a switch.
- **Metrics**: Shows task throughput, output tokens, and input cache hit rate. Double-click to view full values and calculation details.
- **Activity and recovery**: Indicates recent tool calls, subagent dispatches, and waiting for responses. Automatically retries if the conversation-detection helper fails, and explains unavailable data in the details view.
- **Check time**: Refreshes after a successful status check every 30 seconds during an active turn, and immediately when a new usage record arrives. Displays `--` after completion or cancellation.
- **Window controls**: Supports dragging, light and dark themes, manually pinning a conversation, and system tray controls.
- **Background waiting**: Remains in the system tray when Codex is not running and shows the status bar when a Codex window is detected.
- **Start at sign-in**: Offers an optional startup entry for the current Windows user, with no administrator privileges required.

## Quick Start

### Requirements

| Item | Requirement |
| --- | --- |
| Target platform | Windows 11 x64 on an Intel or AMD processor |
| Codex client | A local MSIX installation of the Windows client with package identity `OpenAI.Codex_*` |
| System components | .NET Framework 4.x and Windows UI Automation |
| Python / .NET SDK | Not required to run a release package; the EXE bundles Python, Tk, and the selected-conversation detection helper |

Verified environments include Windows 11 build 26200 x64 with Codex 26.1013.4894.0 and 26.1016.8622.0. See the [compatibility notes (Chinese)](https://github.com/CrAyoN-V587/codex-rate/blob/main/docs/windows11-compatibility.md) for other OS versions, installation methods, and architectures.

### Download and Launch

1. Download the Windows x64 portable ZIP or standalone `CodexRate.exe` from [GitHub Releases](https://github.com/CrAyoN-V587/codex-rate/releases).
2. Place the files in a permanent location. If using the ZIP, extract it completely first.
3. Double-click `CodexRate.exe`. The portable package can also be launched through `Start-Codex-Rate.cmd`.
4. Open Codex, select a local conversation, and wait for the metrics to load.

When Codex is not open, Codex Rate waits in the system tray. The status bar normally hides when Codex is minimized or another application is in the foreground; it stays visible while a menu or details view is open, or while being dragged. When Codex closes, the tool stops reading the conversation and returns to its waiting state.

### Common Actions

| Action | Result |
| --- | --- |
| Drag the status bar | Adjust and save its relative position |
| Double-click the status bar | Open metric details |
| Right-click the status bar or click `⋮` | Open the menu to change the theme, pin a conversation, reset the position, or exit |
| Left-click the tray icon | Open details |
| Right-click the tray icon | Open the menu |

A manually pinned conversation applies only to the current run. Automatic following can be restored from the menu.

### Check Time and Metric Updates

The second line, “上次检测：x秒之前” (last checked: x seconds ago), shows when the current state was last checked successfully. “距最近计量” (time since the latest usage record) in the details view refers to the most recent token usage record. These are different timestamps.

| Conversation state | Time display and metric behavior |
| --- | --- |
| Waiting for the first response or an active turn | Refreshes the check time after a successful check every 30 seconds, and immediately when a new usage record arrives |
| No new usage during tool calls or subagent dispatches | Updates the check time after a successful check and retains the latest trustworthy metrics for the current turn |
| Turn completed | Shows `--` for the check time and retains the final metrics |
| Turn canceled | Shows `--` for both the check time and TPS; retains recorded output tokens and cache hit rate where available |
| Switching conversations, recovering logs, or a read failure | Shows `--` for the check time; all three metrics also show `--` when the current data cannot be confirmed |

Refreshing the check time does not create new token counts or TPS measurements. The check time remains unavailable until the reader has caught up to the end of the log.

## Start at Windows Sign-in

Select “启用开机自启动” (enable startup at sign-in) in the menu to run Codex Rate in the background when the current Windows user signs in. Downloading the application does not register it for startup automatically.

The startup entry uses the `CodexRate` value under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, pointing to the EXE at its permanent location with the `--background` argument. It does not create a system service or scheduled task.

You can also run these commands from the directory containing the EXE:

```powershell
.\CodexRate.exe --install-startup
.\CodexRate.exe --uninstall-startup
```

“退出 Codex Rate” (exit Codex Rate) ends only the current run. To stop it from starting at future sign-ins, select “关闭开机自启动” (disable startup at sign-in) or use the uninstall-startup command above. If you move the EXE, enable startup again to update the path.

## Metrics

Metrics are calculated per task turn as recorded in the Codex logs. A turn may include multiple model responses and tool calls.

| Metric | Definition |
| --- | --- |
| Effective TPS | Total recorded output tokens for the current turn divided by its effective elapsed time, in `tok/s` |
| Turn output | `output_tokens` recorded in the Codex session log, including reasoning output and tool arguments |
| Cache hit rate | This turn's `cached_input_tokens / input_tokens`; cached input is a subset of total input |

Effective elapsed time runs from the start of the turn to the most recent completed model response, minus tool-exclusive time recorded in the log. Overlapping tool intervals are counted once; portions that overlap with explicitly recorded model activity remain included in the elapsed time.

This metric reflects task throughput observed by the client. It includes time to the first token, queuing, and logging delays, and **is not equivalent to server-side decoding speed**. Usage records are generally written after a model response completes. The tool updates its metrics from these records and does not provide token-by-token live speed measurements.

- `~` means the turn is still active and the displayed measurement comes from the most recent completed response.
- “工具” (tool), “代理” (agent), and “等待” (waiting) indicate the most recently observed activity in the main conversation's log. The latest trustworthy measurement for the current turn is retained during tool and agent calls; `--` is shown if no usage record is available yet. These indicators do not represent the real-time execution state of subagents.
- `--` means a metric cannot be calculated or is not ready. All three metrics show `--` while switching conversations, when the selected page cannot be identified, or while data is loading.
- Effective TPS is unavailable if the turn's start is missing, the task was canceled, elapsed time is less than 0.5 seconds, or the data is inconsistent.
- If the turn's start is missing, output tokens and cache hit rate are shown only when trustworthy cumulative values for the current turn are available.

The reader prioritizes the newer `token_usage_record` format and deduplicates records by response ID. The older `token_count` format is supported for compatibility and is not added to the newer format. At startup, the reader searches backward in chunks for the start of the current turn, up to 64 MiB, then restores the turn's records in chunks. Metrics show `--` during recovery and update incrementally afterward. TPS remains unavailable if the start is still missing when the limit is reached.

For records larger than 8 MiB, the reader skips the body if the prefix reliably identifies a known non-metric content type. Corrupt usage records and oversized records with unknown or unidentifiable types are still treated as errors; the next complete turn can restore normal operation. Incomplete lines wait for subsequent writes. The details view shows recovery status, the read backlog, and the number of skipped records.

All three metrics cover only the current conversation. Dispatching a subagent neither clears the main conversation's measurements nor adds subagent output to them. Aggregating parent and child conversations is a [future improvement (Chinese)](https://github.com/CrAyoN-V587/codex-rate/blob/main/docs/roadmap.md).

## Data and Configuration

The tool reads local session logs to extract conversation identifiers, activity types, token counts, and timing information. It does not persist conversation text or display it in the interface, and it does not send session data to external services. It requires no API key, does not proxy model requests, and does not modify Codex installation files, authentication, configuration, or session logs.

| Setting | Location or behavior |
| --- | --- |
| Codex data directory | Uses `--home` first, then `CODEX_HOME`, and otherwise defaults to `.codex` in the user's home directory |
| Status bar settings | `%LOCALAPPDATA%\CodexRate\settings.json`; stores the theme and position |
| Sign-in startup entry | The current user's HKCU Run registry entry, written only when explicitly enabled |

To restore the default theme and position, exit the tool and delete its settings file. This does not affect Codex data.

## Known Limitations

- Automatic following depends on a unique match between a visible navigation item's name and a local conversation's display name. A hidden sidebar, duplicate names, database schema changes, or client interface changes may prevent detection.
- Remote sessions, regular ChatGPT chats, and full multi-window behavior are outside the current validation scope. If another page shares a name with a local conversation, navigation names alone cannot reliably distinguish them.
- The status bar is positioned relative to the bottom of the window and can be adjusted manually. It may not automatically align with the input toolbar in every layout.
- Runtime validation remains incomplete for ARM64, different display scaling levels, mixed DPI, multiple monitors, and startup triggered by an actual Windows sign-in.
- The release EXE is unsigned and does not provide automatic updates. System or organizational application policies may restrict downloading or running it.

See the [Windows 11 compatibility notes (Chinese)](https://github.com/CrAyoN-V587/codex-rate/blob/main/docs/windows11-compatibility.md) for detailed environment requirements and planned compatibility work.

## Development and Build

The build environment used is Python 3.12.7, Tk 8.6, PyInstaller 6.22.3, and the .NET Framework C# compiler included with Windows.

Run from the repository root:

```powershell
# Tests and compilation checks
python -m unittest discover -s tests -v
python -m compileall -q codex_rate run.py package_release.py

# Compile the selected-conversation detection helper and build a single-file EXE
.\build.cmd

# Run from source; complete the build above before the first run
python run.py

# Create a portable ZIP from the built EXE
python package_release.py
```

The Python application uses only the standard library. `build.cmd` installs Python packaging dependencies into the project's `.venv` and writes the EXE to `dist/`; intermediate files are stored in `build/`. These generated directories are excluded from version control.

The following options are available when running from source:

```powershell
python run.py --preview                         # Standalone window using real data
python run.py --demo --preview                  # Synthetic data labeled “演示” (demo)
python run.py --thread YOUR-CONVERSATION-UUID    # Pin a conversation
python run.py --snapshot --thread YOUR-CONVERSATION-UUID
```

`--snapshot` outputs JSON and is best used with the source command; the release EXE has no console and is not suitable for terminal output. Use `--home` to specify the Codex data directory and `--settings` to specify the status bar settings file.

## Validation Status

As of 2026-10-25, v0.3.3 has passed 99 automated tests and Python compilation checks. The stability changes in v0.3.2 have passed an independent code review. Tests cover oversized tool output, recovery of long turns, the recovery limit, partial lines across chunk boundaries, detection-helper restarts and shutdown races, retaining all three metrics during tool activity, 30-second check-time refreshes, and hiding the check time after a turn ends. The automated tests include mocked system interfaces.

Runtime records include agreement between long-turn recovery and a full scan, recovery after terminating the detection helper, timeout-triggered restart after a real pipe blockage, and check-time displays for active and completed conversations. Controlled logs with a real clock confirmed a check-time refresh interval of approximately 30 seconds. Earlier checks also covered switching between local conversations A→B→A, changing themes and exiting through the menu, and launching the portable package from a path containing spaces. See [PROJECT.md (Chinese)](https://github.com/CrAyoN-V587/codex-rate/blob/main/PROJECT.md) for the full record. Other computers, actual Windows sign-in, and multi-monitor setups still require separate validation.

## Design References and Licensing

Design and technical references include [codex-statusbar](https://github.com/dongyue-19/codex-statusbar), [CC Switch](https://github.com/farion1231/cc-switch), [CodexBar](https://github.com/steipete/CodexBar), and [Tokscale](https://github.com/junhoyeo/tokscale). These projects are not distributed as application dependencies.

See [THIRD_PARTY_NOTICES.md (Chinese)](THIRD_PARTY_NOTICES.md) and [licenses/](licenses/) for the sources and licenses of bundled runtime components. No open-source license has been declared for this project's original code.
