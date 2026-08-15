# Phase 1.5 隐性超时扫描

## 扫描范围

本轮扫描线程池超时、延时 Timer、调度循环与网络超时，重点排查“接口已返回超时，但退出路径仍等待后台任务”的隐性阻塞。

## 扫描结论

| 位置 | 模式 | 结论 |
|------|------|------|
| `shell/message_router.py` | 单任务 `ThreadPoolExecutor` | 合格。超时后使用 `shutdown(wait=False, cancel_futures=True)`，不会同步等待正在运行的 handler；新增真实慢 handler 回归测试。 |
| `shell/job_scheduler.py` | 长生命周期线程池 | 合格。停止时设置事件，调度线程仅限时等待 2 秒，线程池不等待运行中任务。 |
| `shell/job_scheduler.py` | cron 下一次执行时间 | 合格。统一使用 `next_after(baseline)`，未发现回拨基线导致同一分钟空转的模式；已有防空转测试。 |
| `shell/ui_host/desktop/app.py` | 延时销毁窗口 Timer | 已修复。Timer 统一登记、显式设为 daemon，并在桌面运行循环退出时统一取消。 |
| `shell/idle_detector.py` | 空闲检测线程 | 合格。使用 daemon 线程、停止事件和有限时长 `join`。 |
| HTTP 与 sidecar 调用 | 客户端/进程超时 | 合格。属于真实 I/O 或进程退出边界，未发现线程池上下文管理器造成的假超时。 |

## 验证重点

- 慢 handler 超时后，调用方在超时窗口附近返回，不等待 handler 自然结束。
- 桌面延时 Timer 可统一取消，且 Timer 不阻止 Python 进程退出。
- 现有 cron 同分钟防空转测试继续通过。
