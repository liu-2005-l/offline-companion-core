# 流式卡片 B4 收口报告

状态：已闭合

版本归属：v1.9.0（未发布）

## 1. 批次终态

| 批次 | 锚 | 核心交付物 | 终态 |
|---|---|---|---|
| B0 | `dcf4a89` | 冻结 B1/B2/B3 接缝、十一项契约与三条显式变更记录 | 已闭合 |
| fixtures | `2237454` | 冻结 23 单例、4 条跨节点不变量链，共 39 个 golden 节点 | 已闭合 |
| B1 | `215716e` | Python 参考解析器、JavaScript 运行时解析器、共享 golden 双实现对账 | 已闭合 |
| B2 | `215716e` | `stream:true` SSE、终态采纳门、canonical plan、全事件持久化与单次 retry | 已闭合 |
| B3 | `215716e` | provisional/accepted/degraded 三态、请求侧开关、gap repair 幂等与断连清理 | 已闭合 |
| B4 | 本报告所在提交 | 双解析器哨兵、候选池裁决、十一项对账与文档同步 | 已闭合 |

## 2. B0 十一项冻结契约对账

| # | 冻结项终态 | 状态 | 判例或记录锚 |
|---|---|---|---|
| 1 | `PartialParse`、七规则、失败统一、complete 单一扫描权威、路径单调与 `steps[i]` 过滤均由双实现完成 | 已实现 | `tests/test_streaming_card_b1_parser.py:32`、`tests/test_streaming_card_b1_golden_fixture.py:46` |
| 2 | 默认同步 JSON 不变，只有 `stream:true` 进入 SSE | 已实现 | `tests/test_plan_card_static.py:183`、`tests/test_desktop_http.py:927` |
| 3 | `card_delta/card_final/card_retry/card_degrade/not_decomposable/error/done` schema 与 provisional/accepted/degraded 生命周期落地；断连 `reset` 生产路径按第 6 项处理 | 已实现 | `tests/test_desktop_http.py:679`、`tests/test_streaming_card_b3_state_runtime.py:13` |
| 4 | card 正文和所有终态均经全库 `seq` 持久化，补拉无类型白名单 | 已实现 | `tests/test_desktop_http.py:679`、`tests/test_desktop_http.py:777`、`tests/test_streaming_card_gap_repair_runtime.py:13` |
| 5 | 开关只决定请求是否携带 `stream:true`，后端不感知 UI 开关 | 已实现 | `tests/test_plan_card_static.py:183` |
| 6 | 连接内 gap repair 已实现且按 `seq <= latestSeq` 幂等；断开续传与 `reset` 不在首版 | 已实现 + 候选池 | `tests/test_streaming_card_gap_repair_runtime.py:13`；候选裁决见本文第 3 节 |
| 7 | 正常、零 delta、retry、终失败、降级、不可拆解与连接内补拉序列落地；retry 预算固定为 1 | 已实现 | `tests/test_desktop_http.py:679`、`tests/test_desktop_http.py:753`、`tests/test_desktop_http.py:777`、`tests/test_desktop_http.py:823`、`tests/test_desktop_http.py:855` |
| 8 | 路径只输出 `steps[i]`，首版保持卡片级闭合；嵌套对象不单独流式 | 已实现；嵌套扩展关闭 | `tests/test_streaming_card_b1_golden_fixture.py:112`；候选裁决见本文第 3 节 |
| 9 | B1/B2/B3 归属未漂移，B2 仅覆盖手动入口，canonical 转换与持久化留在后端 | 已实现 | `tests/test_desktop_http.py:884`、`tests/test_desktop_http.py:940` |
| 10 | Python/JS 共用 39 节点 golden，JavaScript 必须在真实 Node 运行时过账 | 已实现 | `tests/test_streaming_card_b3_js_runtime.py:13` |
| 11 | delta 只承诺有序增量、不承诺 chunk 语义；卡片链不接 A4，`card_final` 才是 accepted 门 | 已实现 | `tests/test_desktop_http.py:699`、`tests/test_streaming_card_b3_state_runtime.py:13` |

本轮没有新增 B0 契约变更。实现遵循原有三条 v1.3 变更记录；候选池裁决不改变首版运行时行为。

## 3. 候选池终态

| 项目 | 去向 | 触发条件或关闭理由 |
|---|---|---|
| 断开续传与 `reset` | v1.9.x 候选池 | 生成生命周期与 HTTP 连接解耦，并具备可恢复的会话/计划标识、最后确认 `seq` 快照和终态补拉后立项 |
| Auto 拆解流式化 | v1.9.x 候选池 | Auto Mode 下次功能批启动且出现第二个流式拆解消费者时抽共享生产器；所有事件必须接 `append_stream_event()` |
| 嵌套对象级流式 | 关闭 | 当前 1.5B 计划 schema 不产出需独立展示的嵌套卡片，提前支持属于 YAGNI；模型/schema 与 UI 需求同时出现后才重开 |

## 4. 显式边界

- 首版只有手动 `/api/plan/decompose` 支持流式；Auto 拆解继续同步。
- HTTP 断开后不继续生成、不续传、不发送 `reset`；B3 清理流式 UI，由用户重发。
- `card_delta` 是 provisional 展示，不等于安全通过；只有 canonical `card_final` 将内容升级为 accepted。
- 卡片流不经过 A4 `PersonaSessionCore` 缓冲审计链；安全边界由生成侧结构约束、终态 C-2 门和前端转义共同承担。
- 嵌套对象不单独流式，`closed` 只暴露直接卡片路径 `steps[i]`。
- 本批未新增浏览器驱动 UI e2e；运行态证据由真实 Node golden/state/gap repair、HTTP SSE 与静态 DOM 接线判例组成。

## 5. 验证

- 全量 pytest：`1508 passed, 3 skipped`。
- 共享 golden：23 单例 + 4 链，共 39 节点；Python 与真实 Node JavaScript 运行时逐字段等值。
- 防回退哨兵：Python 源文件禁止 `json.loads(`，JavaScript 源文件禁止 `JSON.parse(`；两条哨兵均完成临时注入负控红转绿，注入内容未留库。
- SSE 字节契约：`tests/test_desktop_http.py:699` 直接检查原始响应帧 `data: <JSON>\n\n`、无 `event:` 行与 UTF-8 往返。
- retry 预算：`tests/test_desktop_http.py:753` 钉单次 retry 后 accepted，`tests/test_desktop_http.py:777` 钉二次失败以 HTTP 200 内 SSE error 帧终止。
- gap repair：`tests/test_streaming_card_gap_repair_runtime.py:13` 钉补拉 `seq == latestSeq` 不重复累积。
- 解析器哨兵：`tests/test_streaming_card_b1_parser.py:59` 与 `tests/test_streaming_card_b1_parser.py:66`。
