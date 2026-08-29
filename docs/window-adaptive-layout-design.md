# 窗口自适应布局设计 v3

状态：v3 复验归档（2026-08-29）  
范围：桌面壳窗口原生层、前端布局档位、无边框窗口拖拽/缩放与多屏工作区适配。  
事实源口径：窗口核心实现已在先期提交落地，本文件把 v6 引用的方案实体收进仓库，并作为 v1.6.0 G7 的验收锚点。

## 一、目标

- Windows 桌面壳在不同 DPI 与多屏环境下不超屏、不遮任务栏。
- 无边框窗口使用假最大化：铺满当前显示器 `rcWork`，不调用系统最大化态吞掉任务栏边界。
- 拖拽、缩放、还原都使用可解释边界：最小尺寸固定，越界还原会夹回最近工作区。
- 前端布局使用单一 JS 断点源，CSS 只消费 `html[data-layout]` 档位，避免多处 breakpoint 漂移。

## 二、批次拆分

| 批次 | 内容 | 验收 |
| --- | --- | --- |
| D-1 前端档位 | `resolveLayout()` 统一输出 compact / standard / wide，CSS 按 `data-layout` 收缩侧栏、工具栏和面板宽高 | 静态测试锁单一断点源、动态 resize 注册、compact/wide CSS 在场 |
| D-2 原生 DPI | `webview.create_window()` 前调用 `SetProcessDpiAwareness(2)`，失败时降级 `SetProcessDPIAware()` | 单测锁 PM_V1 优先与 system fallback |
| D-3 假最大化 | 获取 HWND 后用 `MonitorFromWindow` + `GetMonitorInfoW.rcWork` + `SetWindowPos` 设置物理像素矩形 | 单测锁多屏工作区、物理像素、还原夹取、HWND 缺失降级 |

## 三、实现锚点

- DPI 入口：`src/offline_companion/shell/ui_host/desktop/app.py` 的 `_ensure_dpi_awareness()`。
- 工作区读取：`_monitor_work_area()` 使用 `MonitorFromWindow(..., MONITOR_DEFAULTTONEAREST)`，`_point_work_area()` 用于还原时按保存矩形中心选屏。
- 假最大化：`WindowAPI._maximize_window()` 保存当前矩形后调用 `_set_window_rect()`，目标为 `rcWork` 的物理像素宽高。
- 还原策略：`WindowAPI._restore_window()` 先找保存矩形所属工作区，再由 `_clamp_restore_rect()` 夹取尺寸和位置。
- 前端档位：`src/offline_companion/shell/ui_host/desktop/static/shell_api.js` 的 `resolveLayout()` 与 `applyAdaptiveLayout()`。

## 四、验证数据归档

| 验证项 | 覆盖数据 | 结果 |
| --- | --- | --- |
| PM_DPI 优先 | `SetProcessDpiAwareness(2)` 调用一次，`SetProcessDPIAware()` 不调用 | 通过 |
| DPI fallback | `SetProcessDpiAwareness(2)` 抛错后调用 `SetProcessDPIAware()` | 通过 |
| 左侧副屏最大化 | 当前窗口 HWND=88，副屏 `rcWork=(-1920,0,0,1040)` | `SetWindowPos(88,-1920,0,1920,1040,0x0014)` |
| 主屏 150% 工作区 | 主屏 fallback `rcWork=(0,0,1707,1019)` | HWND 缺失时 pywebview 降级移动到 `(0,0,1707,1019)` |
| 任务栏变化复核 | 第一次 `rcWork=(0,0,2560,1528)`，复核变为 `(0,0,1920,1040)` | 最大化后重贴到第二个工作区 |
| 越界还原夹取 | 保存矩形 `(-1800,100,2500,1300)`，目标工作区 `(0,0,1280,720)` | 还原为 `(0,0,1280,720)` |
| 前端 compact | `width < 900 || height < 600` | `data-layout="compact"` |
| 前端 wide | `width >= 1600 && height >= 900` | `data-layout="wide"` |

说明：本批不启动真实 GUI，不读取用户屏幕；验证数据来自 `tests/test_desktop_window_api.py` 的 Win32 API fake 与 `tests/test_window_chrome_static.py` 的静态前端哨兵。真实安装包若发布，另按 v1.6.0 G6 在干净 Windows 机执行打包/启动验收。

## 五、v1.6.0 G7 判据

- `tests/test_desktop_window_api.py` 全绿。
- `tests/test_window_chrome_static.py` 全绿。
- `python scripts/full_acceptance.py --skip-gpu` 全绿，其中分层检查保持 `core` 不 import `shell`。
- 本文件保持 v3 状态与验证数据归档，不再悬空引用。

