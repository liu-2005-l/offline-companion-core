# 流式卡片 B0 契约冻结规格

版本：v0.4（冻结稿）

状态：已收口；B1/B2/B3 已实现，B4 对账见 `streaming-card-b4-closure-report.md`

定位：把 v1.3 §2.4 四项锚点展开为 B1/B2/B3 并行时必然对上的接缝规格。

冻结规则：冻结后改契约必须登记提出方、受影响批次与批准记录，不允许批次内静默偏移。

## 0. v0.4 变更摘要

| # | 变更 | 来源 |
|---|---|---|
| 1 | C2.0 流式协商：默认维持同步 JSON，`{goal, stream:true}` 才返回 SSE，既有 `apiJson()` 调用零破坏 | 接缝 1 |
| 2 | `card_final.card` 钉死为 canonical plan projection：完成 `_steps_to_legacy_plan`、context 创建与持久化后，与同步端点 `data.plan` 同构并含 plan id，不是模型原始 JSON | 接缝 2 |
| 3 | 冻结零 delta 序列、`NotDecomposableResult` 复用既有 `not_decomposable` 事件，以及 card 系终态事件一并持久化 | 接缝 3 |
| 4 | 降级计数改为“连续 2 次 `card_delta` 处理后的解析失败”，明确其为传输级 debounce | 非阻断措辞 |

## C1 PartialParse 接口

冻结 B1 对锚实现与 B3 对锚消费：

```text
PartialParse:
  value: dict | None      # autoclose 补全后的解析结果；失败时 None（C1.2）
  closed: list[str]       # 真闭合卡片对象路径，仅 "steps[i]"（C1.4）
  complete: bool          # 三条件定义，见 C1.3
```

### C1.1 autoclose 三阶段管线

阶段一，扫描：O(n) 单趟确定 lexer 状态，包括 `in_string`、`escape`、结构栈与未完成 token 类型。

阶段二，按序修复 token 与键值对：

1. 未完成转义（尾部 `\` 或 `\u` 加不足 4 个 hex）时，回退到转义起点；
2. 未闭合 string（奇数未转义引号）时，补 `"`；
3. 尾部悬挂逗号时，防御性剔除；
4. 未完成值 token（literal 前缀 `tru`、`fals`、`nul`，数字前缀 `1e`、`-`、`1.`；适用对象值位与数组元素位）时，丢弃该 token、值位补 `null` 并保留键；
5. 冒号后空值位，即 `:` 后没有任何 token 时，值位补 `null`；
6. 未完成键值对，包括键名未完成 `{"ste` 或键名完成但缺冒号 `{"a"` 时，丢弃该键值对。

阶段三，闭合：按结构栈逆序补全未闭合的 `{`、`[`；值位或元素位上已经开始的嵌套容器由此补成合法空容器 `{}`、`[]`。数组空位不补 `null`，以保持路径单调。

**顺序约束**：修复必须先于闭合。先闭合会产出 `{"a":}` 等非法结构，使修复规则失去作用点。

### C1.2 语义保证与失败统一

- **路径集合单调**：后一 buffer 的 `value` 键/路径集合是前一 buffer 的超集，`closed` 集合单调不减；值本身不承诺单调，`null → 真值`、`前缀 → 全串`、`null → 对象` 均合法。
- **空位不占位**：数组 `[` 后或悬挂逗号后不产生元素路径；元素路径仅在元素 token 已开始后出现，此后不消失。
- **失败统一**：三阶段管线后仍不能产出合法 JSON 的前缀均为失败，包括首个非空白字符不是 `{`、括号类型不匹配等不可恢复形态。
- **失败结果**：返回 `PartialParse{value:None, closed:[], complete:False}`。
- **UI 状态归属**：B3 收到失败结果时保留本地已渲染状态；解析器不持有 UI 状态。
- **降级计数**：每个 `card_delta` 累积 buffer 后调用 B1；连续 2 次处理均失败时触发 `card_degrade`，任一成功处理清零计数。该计数只是传输级 debounce，不赋予 chunk 内容语义。

### C1.3 complete 定义

```text
complete = 原文可 json.loads 为 dict
           ∧ 无未完成词法状态
           ∧ 结构栈空且无栈下溢
```

三项并列为实现规范。`struct-scan` 独立判定，不得仅凭试解析成功得出 `complete`；栈下溢等结构非法走 C1.2 失败路径。

### C1.4 struct-scan 规范

`struct-scan` 是 O(n) 单趟状态机，维护 `in_string`、`escape`、结构栈与当前路径；结构栈每层包含容器类型、所属键名和数组索引。

- 遇到配对闭合符时弹栈并回退路径；内部追踪全部对象，但 `closed` 仅输出 `steps[<int>]` 形式的卡片路径。嵌套对象与顶层根对象一律不进入 `closed`，与 C4 互锁；
- 数组索引随 `[` 重置、随 `,` 递增；键名在 string 完整闭合且后随 `:` 时进入路径；
- string 内任意字符不参与结构状态；
- L0 在扫描识别到顶层对象键 token `steps` 完整闭合并后随 `:` 与 `[` 时触发，不做字符串外字样匹配；
- 输出为 `closed_paths + open_stack`。

## C2 SSE 事件族

冻结 B2 产出与 B3 消费。

### C2.0 流式协商

`POST /api/plan/decompose`：

- 默认请求，即没有 `stream` 或 `stream:false`，维持现有同步 JSON 响应，既有 `apiJson()` 调用与存量调用方行为不变；
- `{goal, stream:true}` 返回 C2 定义的 SSE card 序列；
- B3 开启流式卡片时发送 `stream:true`，关闭时发送默认同步请求；后端只按 `stream` 参数选择响应模式，不感知前端开关本体。

### C2.1 事件 schema 与生命周期

帧格式为 `data: <JSON>\n\n`，不使用命名 SSE `event:`；事件类型由 `payload.type` 表示，前端按 `type` 路由。

| type | payload | 语义 |
|---|---|---|
| `card_delta` | `{type, seq, delta}` | `delta` 是非累积、有序增量文本片段，chunk 边界不具语义。由 delta 渲染的内容均处于 provisional 态 |
| `card_final` | `{type, seq, card}` | 终态采纳门；C-2 通过后发送。`card` 是完成 `_steps_to_legacy_plan`、context 创建与持久化后的 canonical plan projection，与同步端点 `data.plan` 同构并含 plan id，不是模型原始 JSON。前端以 `card` 刷新 provisional 渲染，升级为 accepted 后折叠并落事件流 |
| `card_retry` | `{type, seq, attempt}` | `attempt` 是生成序号：首次生成是 1，首次重试是 2。前端清空本 attempt 的全部 provisional 内容、保留容器骨架，并明示“重新生成中（第 attempt 次）” |
| `card_degrade` | `{type, seq, reason}` | 中途跑飞降级。已闭合卡片保留显示，但标记为 degraded/provisional；生长区切换为纯文本，且永久不切回 |
| `not_decomposable` | `{type, seq, status, reason, fallback_notice, done:true}` | 复用既有 `NotDecomposableResult` 事件。无法拆解时以本事件收尾，不误报 `card_validation_failed`；前端走既有不可拆解分支 |
| `error` | `{type, seq, code:"card_validation_failed", done:true}` | 最终 attempt 仍未通过 C-2 时发送，不发 `card_final`。本 attempt 的 provisional 卡片保留并标注“校验未通过，内容可能不准确”，转为 degraded 视觉态 |

非 card 系 `done`、`error` 维持现有语义；同轮内 `card_final` 先于 `done`。

**术语纪律**：`card_delta` 流出不等于安全通过。delta 是 provisional 展示，是否 accepted 由 `card_final` 裁决。“安全检查通过后才流出”只适用于 A4 等缓冲回放链路；卡片流对应的是终态采纳门，二者不得混称。

### C2.2 seq 接入与持久化

- card 流全部事件，包括 `card_delta`、`card_final`、`card_retry`、`card_degrade`、`not_decomposable`、`error`，必须经 `append_stream_event()` 获得全库自增 `seq` 并持久化；终态事件不得遗漏；
- Auto 事件当前直接发送、未持久化且没有 `seq`，该例外不适用于首版手动 card 流。未来若流式化 Auto，必须同样接入 `append_stream_event()`；
- `stream_events_after()` 不设类型白名单，card 事件持久化后，连接内 gap repair 自动覆盖正文与终态事件。

### C2.3 开关归属

开关等价于请求侧协商：关闭时前端发送默认同步请求并整卡渲染；开启时发送 `stream:true`。后端按 `stream` 参数选择响应模式，不感知开关本体；非流式路径行为不变。

### C2.4 断连续传

- B2 只交付连接内 gap repair：按 `lastSeq` 补拉已持久化的 card 事件，包括终态事件；
- 断开续传与 `reset` 协议依赖生成生命周期和 HTTP 连接解耦，首版不做，进入候选池；
- 首版断开行为沿用请求失败兜底：清理流式 UI，由用户重发，不劣于现状。

## C3 事件序列

```text
LLM 正常:   card_delta*（provisional）→ card_final（canonical projection → accepted）→ done
零 delta:   card_final（builtin/rule 命中）→ done
retry:      card_delta* → card_retry{attempt:2} → card_delta*
            → card_final ｜ error{card_validation_failed}
降级:       card_delta{1..k} → card_degrade → 纯文本 → done
不可拆解:   card_delta* ｜ 空 → not_decomposable{status, reason, fallback_notice, done:true}
连接内补拉: [丢帧] → gap repair（lastSeq 补拉正文与终态）→ 流继续
断开:       流中断 → 请求失败兜底（首版无续传）
```

- B3 必须容忍零 delta 序列：L0/L1 可以从未出现，直接以 `card_final.card` 落 L2；
- card 重试预算固定为 1，生成 attempt 总数为 2，对齐现有质量校验一次 retry、二次失败进终态的纪律，不新增可调参数；
- retry 后的重生成不保证前缀一致，不得累积跨 attempt 的 delta；
- 降级后永久不切回；终态 `error` 保留 provisional 卡片并标错，不使内容蒸发；
- builtin/rule 命中允许零 `card_delta` 直接发送 `card_final`；无法拆解走 `not_decomposable`，两者都不得误报 `card_validation_failed`。

## C4 路径表示法与闭合粒度

- 路径采用 JSONPath 子集，仅支持对象键与数组索引，`$` 可省；`closed` 元素是 `steps[i]` 形式的路径字符串；
- 首版只支持卡片级闭合：卡片对象是 `steps[]` 的直接元素，真闭合即进入 L2；嵌套对象不单独流式；
- 本地 GBNF schema 把 `steps` 放在第一个数组型顶层键；其他顶层键序不承诺。云端键序不保证，L0 时点不承诺，只承诺 L2 语义一致。

## D1 批次对接矩阵

| 批次 | 产出 | 消费 | 载体 |
|---|---|---|---|
| B1 | `autoclose` 三阶段、`struct-scan`、`PartialParse` | 无；纯函数，buffer 由调用方持有，无 IO、无状态 | Python 参考实现 + JS 运行时 |
| B2 | C2.0 流式协商、C2 全事件族与终态持久化、连接内 gap repair、`card_final` 终态采纳门、终失败 `error` | 不做增量解析；发 `card_final` 前完成最终解析、C-2、`_steps_to_legacy_plan` 转换与持久化 | Python |
| B3 | L0-L2 分级、provisional/accepted/degraded 三态、零 delta 容忍、空结构、滚动跟随、请求侧开关 | C2 全事件族；持有 buffer、调用 B1、保留解析失败时的本地 UI 状态 | JS |

### D1.1 B2 覆盖范围

首版仅覆盖手动入口：

```text
/api/plan/decompose + stream:true
  → decompose_with_llm() 流式输出
  → card_delta 经 append_stream_event()
  → 完整 JSON 后执行 C-2
  → _steps_to_legacy_plan + context 创建 + 持久化
  → card_final（canonical projection）或 error
```

builtin/rule 与 `NotDecomposableResult` 分别按 C3 发送零 delta `card_final` 或 `not_decomposable`。

Auto 拆解维持现状：`/api/chat` → `AutoTurnOrchestrator` 独立同步拆解。Auto 流式化进入候选池，原因是 B2 首版量级有限、Auto 后台执行缺少持续观看生成的高收益场景，且单消费者阶段不提前抽共享流式生产器。未来流式化 Auto 时必须接入 `append_stream_event()`。

## D2 B1 语言与测试载体

- Python 参考实现由 pytest 全覆盖并持有语义主权；
- JS 运行时移植与 Python 实现共同消费同一份 JSON golden fixtures；
- B1 闭合门槛是 Python pytest 语义闭合；
- JS 运行态 golden 对账是 B3 合并门槛，不得以静态源码断言代替；
- B3 e2e 在 Phase 5 UI 自动化链路二次覆盖关键路径。

## D3 卡片流安全语义

- `delta` 是非累积、有序增量文本片段，chunk 边界不具语义。前端不得据此推断分词、词级平滑或时序，一切解析基于累积 buffer；
- 卡片流不接 A4 或 `PersonaSessionCore`。安全语义由生成侧结构约束（本地 GBNF 或云端 JSON mode）、终态采纳门（`card_final` 前最终解析、C-2 与 canonical 转换）和渲染层 XSS escape 共同组成；
- 未来若为 delta 流引入等价增量安全扫描，推送时点必须在扫描通过之后，与 A4 规格的安全纪律一致。

## E 冻结项清单

| # | 冻结项 | 条款 |
|---|---|---|
| 1 | `PartialParse` 三字段、autoclose 三阶段七规则、失败统一、路径集合单调、complete 三条件、struct-scan 路径栈与仅 `steps[i]` 的 closed 过滤 | C1 |
| 2 | 默认同步 JSON、`stream:true` 才启用 SSE 的流式协商 | C2.0 |
| 3 | 七事件 schema、canonical `card_final.card`、三态生命周期、attempt 生成序号、终态标错不清除与 `not_decomposable` 复用 | C2.1 |
| 4 | card 流全部事件与终态接入 `append_stream_event()`，连接内 gap repair 覆盖终态 | C2.2 |
| 5 | 开关归属请求侧协商，后端不感知开关本体 | C2.3 |
| 6 | 连接内 gap repair 属 B2；断开续传与 `reset` 首版不做 | C2.4 |
| 7 | 六条事件序列、三态生命周期与 card 重试预算 1 | C3 |
| 8 | 路径表示法、卡片级闭合粒度与顶层键序 | C4 |
| 9 | D1 对接矩阵、仅手动入口的 B2 范围与 canonical 转换归属 | D1 |
| 10 | B1 双语言载体与 JS 运行态 golden 的 B3 合并门槛 | D2 |
| 11 | 无语义 delta 边界、不接 A4 与终态采纳门 | D3 |

不冻结、由批次内部决定的内容：autoclose/struct-scan 内部算法、渲染 DOM 结构、SSE 帧包装细节、C-2 校验内部实现。

## F 对 v1.3 的变更记录

1. §5.1 `reset` 模式首版不做，进入候选池；
2. delta 从“token 级”改为“增量片段、边界无语义”；
3. §2.3 从“解析失败返回上一次成功 `PartialParse`”改为“失败返回 `None`，旧 UI 由调用方保留”。

候选池终态：

- 断开续传与 `reset` 协议保留至 v1.9.x；触发条件是生成生命周期与 HTTP 连接解耦，并具备可恢复的会话/计划标识、最后确认 `seq` 快照和终态补拉；
- Auto 拆解流式化保留至 v1.9.x；触发条件是 Auto Mode 下次功能批启动且出现第二个流式拆解消费者，届时抽取共享生产器并接入 `append_stream_event()`；
- 卡片嵌套对象级流式关闭；当前 1.5B 计划 schema 不产出需要独立展示的嵌套卡片，仅当模型/schema 与 UI 需求同时出现时重新立项。

## G 执行顺序

B0 冻结后，B1、B2、B3 已按本契约并行实现并由 B4 完成收口；后续契约变化必须继续写入本文件变更记录。
