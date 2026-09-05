# 人格约束 P3 接线批规格

版本：v1.3（P3-0 标定判定线联动修订稿）
状态：主体规格已展开；L2 数值包与 L3 强度语义仍须 P3-0 预注册，尚未实现、未锚定
上游：`docs/persona-constraint-batch-design-v1_5.md`、`configs/persona_constraint_corpus.yaml`、
P1 锚 `bcb8c1a`、P2 闭合锚 `658fdb3`

## 0. Repo trace 修订结论

| 骨架项 | Repo 事实 | v1.2 裁决 |
| --- | --- | --- |
| L2 参数顺延 W3 | v1.5 §8.3 明确参数包不入 W3；当前两种本地后端也没有逐请求采样参数入口 | 不顺延 W3，也不擅自移出 P 批；新增 P3-0 数值与协议锚，冻结后再接 P3/P4 |
| 三审计事件注册即可触发 | 三个事件均不在 `DEFAULT_EVENT_TYPES`，当前也没有生产者；算术审计发生在首次生成之后 | 规范名、生产点、消费时序和直接信号通路一起落地；EventStream 只做审计镜像，不作为触发唯一事实源 |
| persona 切换只改激活 API | 当前激活会原地替换 `session_core`；“新建会话”实际调用 `/api/clear`；历史会话选择只换前端列表，不换后端 runtime | 新增原子会话绑定服务，统一处理创建、恢复、persona 切换和事件流重绑定 |
| 移除 traits UI 即无旁路 | `POST/PUT /api/personas` 与 `persona_repo.py` 仍接受任意 `traits`；JS 派生切点为 `<=35/>=70`，与冻结 `33/34/66/67` 不同 | 仓储/API 写入口一并收口；后端派生是唯一实现，前端不再自带第二套阈值 |
| OCEAN 只预留、不做 UI | 当前新建人格已有可拖拽雷达，编辑页已有 `0..100` 数字输入 | 不新增编辑 UI，但保留现有入口并标记验证状态；编辑 active persona 只影响后续新会话 |
| 25 条确定性文案 | 骨架只列 switch/确认/降级三类，按五人格应为 `3×5=15` | 配额修正为 15；安全、Consent、审计警示等保护区文案不得人格化 |
| P3 完全不接 L4 | P2 载体裁决书明确要求 P3 接通 L4 retry/fallback；现有流式路径会先发原始 token，再产出审计后的最终文本 | P3 接通 P1 冻结检测器与动作链，并对约束会话先缓冲后放行；W3 只负责检测器改造、扩域与指标重校 |
| 五标定点可直接覆盖现有人格 | 当前三个人格的 OCEAN 档位签名均不命中五个冻结标定点 | 保留三个人格与用户向量，不暗改 OCEAN；另把五个冻结标定点作为可选预设物理入库，否则 P3 没有可见的已验证入口 |
| `sessions.persona_id` 足以保证会话边界 | 会话表只存 ID；persona 被编辑或删除后，历史会话无法恢复创建时配置 | 会话创建时持久化版本化 persona 快照；旧会话迁移不得用当前 persona 静默冒充历史快照 |
| `configs_dir()` 可直接承载冻结语料 | 便携版首次启动后不再同步 configs，旧数据目录会遮住新版内置资产 | 人格约束资产按“完整根”解析并校验哈希，禁止跨根拼接；旧 seeded root 不完整时整体回退新版 bundled root |
| L2/L3 已有可实现参数 | P1 只冻结档位、`set_style_strength_low` 语义名与触发条件，没有解码增量表、叠加/夹紧规则或 L3 机器效果 | 设 P3-0 阻塞锚：数值与效果先预注册，再改推理协议；不得用未测全零或空转字段冒充接线，数据确认的全零走不采用裁决 |

本规格中的“接线”覆盖输入组装、L2/L3 调制、P1 冻结 L4 基线动作链、状态派生和 A 层会话 UX。
W3 独占的是输出检测器的后续改造、检测域扩展、4-gram 重校与跨轮结构修复，不得把 P3 已承诺的
`retry_then_fallback` 基线接线顺延给 W3。

## 1. 分层与新增边界

### 1.1 B 层：人格约束核心

在 `core/persona_constraint/` 建立单一实现入口，职责固定为：

- 加载并校验 `persona_constraint_corpus.yaml` 及其五份事实源；
- 规范化 OCEAN，按 `O,C,E,A,N` 派生 low/mid/high；
- 识别五个冻结标定点或 `unvalidated_custom`；
- 选择 L1 维度/结构样本，解析 L3 降档信号并稳定渲染 system 文本块；
- 执行 P1 冻结 L4 三分区扫描并返回结构化动作，不在 A 层复制正则；
- 提供语料 lint 与展示 traits 派生函数。

B 层不得 import `shell`，不得访问网络，不直接写 UI 设置。配置候选根复用 `runtime_paths`，但人格约束资产必须
通过 §1.4 的专用完整根 resolver 选择，不能直接取一次 `configs_dir()` 后逐文件兜底。

### 1.2 A 层：迁移与会话切换编排

在 `shell/` 建立服务层，负责：

- 调用 B 层派生器后把缓存写入存储；
- 导出存量手写 traits，并编排一次性迁移；
- 原子创建/绑定会话、更新单一 session context 与前端响应；
- 把算术/质量审计事实转换为显式 `PersonaTurnSignals`，同时镜像到 EventStream。

### 1.3 C/存储边界

`storage/persona_repo.py` 继续只做 SQLite 持久化，不 import B 层。公开创建/更新路径不得再接受用户提供的
`traits`；仅允许 A 层传入命名明确的 `derived_traits_cache`。收到外部 `traits` 时返回
`traits_read_only`，禁止静默忽略。

当前 `InferenceBackend.generate/generate_stream` 没有逐请求采样参数入口。P3 是否扩展为共享
`GenerationOptions` DTO，取决于 §5 的 P3-0 数值包锚；在数值包冻结前禁止先改 C 层接口，也禁止把 L2
静默改判为开放调节批。

### 1.4 冻结资产解析边界

人格约束 loader 不直接相信 `configs_dir()` 返回的整棵目录，而是按候选根逐个验证统一入口、全部引用、schema
版本与源文件 SHA-256。只有同一候选根内全部资产完整且哈希一致时才选择该根，禁止“manifest 来自 seeded、
缺失文件来自 bundled”的跨根拼接。

候选顺序为：显式测试/开发 override → 完整的数据目录根 → PyInstaller bundled 根 → repo 根。旧便携数据目录只含
旧 configs 时必须整体跳过并使用新版 bundled 根。`sources` 路径相对候选根解析，拒绝绝对路径与 `..` 越界。
P3-A 必须给 `persona_constraint_corpus.yaml` 增加源文件哈希，并覆盖“旧 seeded root 遮挡新版资产”的升级回归。

## 2. 单一派生链与标定点

### 2.1 顺序、切点与结果类型

- 唯一顺序常量：`OCEAN_DIMENSION_ORDER = ("O", "C", "E", "A", "N")`；
- DB/API/UI 输入为五项 `0..100` 整数数组；YAML 输入为全名键 `0..1`，两者先归一化为 `OceanVector`；
- 唯一切点：`0..33=low`、`34..66=mid`、`67..100=high`；
- `to_level()` 只接受已校验的维度和值，不合法值抛配置错误，不在派生层偷偷夹紧；
- 输出 `PersonaConstraintProfile` 至少包含顺序化档位、匹配 trait、验证状态、L1 配置编号和关闭原因。

### 2.2 五标定点与自定义向量

按五维档位签名匹配 `persona_constraint_mappings.yaml`：

- 唯一命中温柔/暴躁/可靠/甜美/可爱之一：`validated_anchor`，允许接入 P2 L1/L3；
- 无命中：`unvalidated_custom`，保留 OCEAN 与展示，但人格约束默认关闭，输出必须与同 seed 无约束路径一致；
- 多命中：配置错误，整体关闭人格约束。lint 必须保证冻结五标定点档位签名唯一。

`traits_json` 目标态缓存只保存匹配到的冻结 trait，未验证自定义向量保存空列表；UI 另行展示
“自定义 OCEAN · 未验证”，不得把状态字样塞进 traits 缓存。

P3 必须把温柔、暴躁、可靠、甜美、可爱五个冻结组合作为版本化内置预设写入 persona 注册表，并以稳定 ID
区分于 display name。现有小诺、阿策、知心和全部用户人格一律保留为 `unvalidated_custom`，不得为了命中标定点
重写其 OCEAN。内置预设被用户编辑时必须“另存为”新的自定义人格，禁止原地篡改冻结预设。

### 2.3 派生与迁移测试

- 五维 × `33/34/66/67` 共 20 个边界断言；
- DB 数组与 YAML 映射归一化后逐字段一致；
- 五标定点唯一命中，甜美/可爱 A 一档差、温柔/甜美 E 两档差断言保留；
- 同输入连续两次派生的结构化结果和稳定 JSON 逐字节一致；
- 无效长度、NaN、布尔值、越界值和未知维度全部明确失败。

## 3. traits 迁移三件套

### 3.1 导出先于覆盖

第一次迁移前，把 personas 表全部记录的 `id/name/traits_json/ocean_json/updated_at` 导出到当前 runtime 注入的
`AppPaths.exports_dir/persona_traits_migration_v1.json`。禁止直接调用全局 `data_root()`，否则 `--data-dir` 与测试
隔离会导出到错误用户目录。无法可靠区分手写与旧自动产物，因此全量导出，不猜作者。

导出文件包含 schema 版本、记录数、逐条原文与 SHA-256；使用临时文件 + 原子替换。导出失败、数量不符或
哈希复算不符时，数据库零修改。已有成功导出不得覆盖。

### 3.2 幂等迁移记录

新增持久化迁移记录 `persona_traits_to_ocean_v1`，状态只允许 `exported/completed`。流程为：

1. 完成并校验导出；
2. 对每条 persona 用 OCEAN 派生缓存；
3. 单一数据库事务更新 `traits_json` 与 `raw_json.traits`；
4. 写入 `completed`、导出路径、数量与哈希。

重复启动看到 `completed` 时只做一致性 lint，不重复导出、不重复改写。中断在 `exported` 时复用已校验文件重试。
迁移成功后的首次 UI 响应必须返回导出路径与记录数，前端明确提示“原风格标签已导出并转换”，不得只写日志。

### 3.3 写入口收口

- 前端移除 traits chip 编辑器和提交字段；
- API create/update 收到 `traits` 返回 400 `traits_read_only`；
- 新建/更新 OCEAN 后由后端重算 `traits_json` 与 `raw_json.traits`；
- `shell.js::_deriveTraits()` 及其 `35/70` 阈值删除，所有展示只消费 API 返回缓存；
- `tone_keywords` 保持 reformatter 行为字段，不回退为 traits，不参与本迁移。

验收必须覆盖：导出数量、原文保全、哈希、故障零覆盖、断点恢复、二次运行幂等、API 旁路拒绝和
`traits_json/raw_json.traits` 一致。

## 4. L1 选择与组装预算

### 4.1 确定性选择

对 `validated_anchor` 每轮最多组装六个完整文本块：

1. O/C/E/A/N 各一段完整 2–3 轮微型对话，顺序固定；
2. 一条结构样本。

维度对话从该人格冻结引用中选择：当前场景有同类候选时取同类候选，否则取 YAML 中第一条。场景分类只使用
已有 emotion label、身份意图、审计信号和小型确定性关键词族；分类器失败回 `general`，不得调用模型选样本。

结构样本优先级：`low_intensity_correction` > `low_intensity_comfort` > 身份/能力诚实 > 纠偏 > 默认诚实。
同级按 composition YAML 顺序取第一条。所有选择结果写入 trace 编号。

### 4.2 预算与失败语义

- 渲染后 L1 文本硬上限 `640` 个 Unicode 字符，不含既有身份锁、skill、memory 与格式提示；
- 只按完整块组装，禁止截断某条示例；
- 五维 + 一结构任一标定点超过 640 字符视为配置错误，关闭整个人格约束，不通过丢维度“凑预算”；
- P3 fixture 必须证明五标定点当前最坏组合均不超过上限；P4 另记真实 GGUF prompt token 数。

组装位置沿用臂 A：身份锁、算术要求、skill prompt 之后追加人格 L1 块，再拼现有 tone/emotion/format hint。
人格块不得覆盖安全、审计、Consent 或 skill 约束。

## 5. L2 参数包：P3-0 阻塞锚

v1.5 把本批定义为五标定点批，并明确 P3 接 L2、P4 锁定 L2/L4；§8.3 只排除了 W3，不授权把 L2 顺延到
开放调节批。当前 repo 没有参数包 YAML，也没有逐请求采样参数协议，因此本规格不能假装 L2 已可实现。

P3-0 必须先冻结一份机器规格，至少包含：

- 每维 low/mid/high 的 `temperature/top_p/repeat_penalty` 增量或显式 `no_change`；
- 五维叠加顺序、最终夹紧区间、非法组合与后端不支持时的确定性关闭语义；
- L1 注入预算是否属于 L2，以及它与 §4 固定 `640` 字符上限的关系；
- 本地 server、本地直调、云端路由各自的支持矩阵和 applied-options trace；
- P4 逐项归因所需的 baseline、只开 L1、只开 L2、L1+L2 观察臂。

若 P3-0 至少确认一个非零 delta，再新增共享不可变 `GenerationOptions`，默认值与现有路径逐字节/逐参数等价；
只有 `validated_anchor` 能应用确认增量。若十个 low/high 格全部为 `screened_no_candidate/confirmed_no_effect`，
L2 形成 `no_effect_observed_within_preregistered_grid` 不采用裁决，P3-A 不为人格功能新增该 DTO。任何后端不能
证明参数已应用时，返回 `l2_unsupported` 并关闭整个人格约束，不得吞掉参数继续宣称 L2 生效。

## 6. L3 强度、降档信号与审计事件

### 6.1 L3 机器语义：P3-0 阻塞锚

P1 只冻结 `set_style_strength_low/keep_derived_style_strength` 名称，没有冻结“低强度”在运行时具体改变什么。
P3-0 必须把 L3 限定为不改事实语义的确定性表达参数，并逐字段定义标准档、低档与保护区：例如句段拆分上限、
语气标记配额、感叹号上限和 hedging 允许集。不得通过删句、改数字、替换能力边界或追加未证实承诺实现降档。

模型候选先完成算术/质量审计及其最多一次 retry，再执行 L3 仅表达变换与 L4 扫描，最终通过后才能持久化/返回；
L4 自身的最多一次 retry 也必须重新经过适用审计、L3 与 L4，禁止形成递归重试。安全固定回复、Consent、算术警示、
审计块、任务结果与错误码绕过 L3 并逐字节透传。L3 规格须有逐字段正负控和“事实槽位不变”断言。

### 6.2 触发事实源

新增不可变 `PersonaTurnSignals`，由调用方显式传入 B 层组装器。EventStream 只记录同一事实，不得成为唯一
触发源，避免 `_append_domain_event()` 的既有 fail-open 行为把人格降档静默吃掉。

三规范信号及生产时点：

| 信号 | 真实来源 | 消费时点 |
| --- | --- | --- |
| `audit/arithmetic_retry_taken` | 算术首次审计失败且即将调用 retry | 当前 retry 生成，使用低强度纠错样本 |
| `audit/arithmetic_warning_appended` | 无可用 retry 或 retry 后仍失败并追加确定性警示 | 警示本身不人格化；下一次模型生成最多消费一次 |
| `audit/quality_retry_taken` | `quality_retry_counts` 从 0 增到 1 | 同 trace 下一次模型生成或最终摘要生成 |

规范事件加入 `DEFAULT_EVENT_TYPES`，payload 至少含 `session_id/trace_id/source/consumed_in_turn`。事件追加失败只影响
审计可见性；显式信号仍必须生效并在组装 trace 标记 `event_mirror_failed`。

### 6.3 情绪双阈值

- `sadness/anxiety/anger/disgust` 且 `0.45 <= confidence < 0.70` → `low_intensity_comfort`；
- `confidence >= 0.70` → 标准强度；低于 0.45、neutral 或未知标签不触发；
- 审计纠错优先于情绪共情；边界值与优先级按 P1 fixture 原样复用。

`arithmetic_warning_appended` 的下一轮一次性消费必须从最近 assistant message meta 读取；消费过或中间已有新的
assistant 回复则不再触发，禁止无限降档。进程重启后仍可由消息 meta 恢复，不依赖内存游标。

### 6.4 P1 冻结 L4 基线动作链

P3 接通 `persona_constraint_l4_patterns.yaml` 的三分区动作：身份断崖与能力/事实否认走
`retry_then_fallback`，攻击用户区只记 `observe_only` warning。首次命中后的 retry 必须增加准确优先与人格内诚实
提醒；retry 仍命中时返回确定性降级文案，失败输出不得写消息表、不得进入记忆抽取、不得暴露给前端。

约束会话的 SSE 路径在 P3 采用“后端生成缓冲 → L3 → L4 → 审计后分块回放”，不能像现状一样先发送原始 token
再在 `done` 事件替换。该路径保留 SSE 传输但不宣称真流；恢复低延迟且可安全在线扫描的输出侧方案归 W3。
P4 必须单列 F0b `11/80` 禁用族、F0a `6/18` 断崖本底、assistant 复制与 user 示例泄漏。

## 7. lint 常驻化

在 B 层提供纯函数 lint，在 `scripts/ci/` 增加仓库入口并接入现有 CI。检查项分开报告错误码：

- 事实源存在、schema 版本、引用完整性、标定点唯一、预算与稳定顺序；
- 统一入口全部源文件哈希、完整根选择与路径不越界；
- lexicon 禁用族、L4 静态模式、具体 display name、分歧占比；
- 无证据绝对承诺与内部机制泄漏；
- 复制 detector 历史正控和逐结构样本正控。

短前缀复制正控只验证 detector，不把“静态语料未复制自身”当作运行时零复制证明。

正控 fixture 必须放在测试目录，不混入生产配置。至少逐项注入：禁用身份、L4 能力否认、具体名字、绝对承诺、
内部参数泄漏、悬空引用和超预算组合。每条必须命中**预期错误码**，不能靠其他规则蹭红；另配模式近邻负控。

## 8. 确定性路径人格化文案

骨架列出的配额修正为三类 × 五人格 = 15 条：

1. persona 切换成功提示；
2. 记忆保存确认语；
3. 人格约束配置异常后的用户可见降级提示。

15 条均从独立 YAML 加载，过禁用/L4/绝对承诺/内部机制泄漏 lint。身份查询继续使用现有安全
`display_name` 参数化模板，不复制成五份；人格差异由当前 profile 的短语片段提供。

以下保护区逐字节不变且明确排除人格化：安全固定回复、Consent 文案、算术警示、审计块、任务结果与错误码。
“可靠”不得通过改写这些保护区制造行为差异。

## 9. Persona 切换与真实会话边界

### 9.1 会话事实源

会话绑定事实源是 `sessions.persona_id + persona_snapshot_json + persona_snapshot_schema`。`persona_id` 用于来源追踪，
版本化快照才用于恢复该会话的 `PersonaSessionCore`；personas 表的 `active` 只表示“下一新会话默认人格”。恢复
历史会话不得读取当前 persona 覆盖快照。

P3 数据库迁移为现存会话回填快照：能找到 persona 时记录 `legacy_backfill` 来源；找不到 persona 的孤儿会话只允许
查看历史，恢复聊天返回 `persona_snapshot_missing`，由用户显式选择人格后创建新会话。禁止拿全局 active 静默补洞。

### 9.2 原子绑定服务

当前 bootstrap 把初始 `session_id/event_stream` 捕获进 sample、consent、tool、plan publisher 与 memory idle closure，
逐字段改 `runtime.session_id` 无法形成完整切换。P3 新增不可变 `DesktopSessionContext`，所有每轮入口先在锁内捕获同一
context；长生命周期组件只持 context provider，不再持裸 session ID 或裸 EventStream。

新增单点 `bind_desktop_session()`，正常切换 persona 时：

1. 在无进行中生成/计划写入时获取切换锁；忙时返回 409，零状态变化；
2. 校验目标 persona，生成规范快照，预构造 `PersonaSessionCore`、目标 EventStream 与完整 context；
3. 在一个 SQLite 事务中新建 session、写快照、更新 personas.active，并更新 SQLite 内的 canonical
   `active_session_id`；
4. 事务提交后只做一次不可抛错的 context 指针替换；所有后续 turn 使用新 context，已开始 turn 保持旧 context；
5. 成功响应返回实际 persona、实际新 `session_id`、快照版本和 `created_new_session=true`。

`settings.json` 的 `active_persona_id/active_session_id` 不再是事实源；P3 可迁移删除或作为可重建兼容投影，但不得把
跨 SQLite/JSON 的补偿写伪装成原子事务。进程若在 DB 提交后、内存替换前退出，重启必须从 SQLite canonical 指针
恢复。任一步在事务提交前失败则数据库与 context 均零变化，前端不改 chip、`_currentSessionId` 或本地设置。

### 9.3 API 与前端行为

- `/api/personas/<id>/activate` 改为创建并绑定新会话，不再原地换 `session_core`；
- 新增历史会话激活 API，按 `sessions.persona_id` 完整重绑定 runtime；
- 应用启动先读取 SQLite `active_session_id` 与 persona 快照；删除当前按全局 active 强行替换 `session_core` 的路径；
- “新建会话”改为真实创建 session；清空当前会话继续单独使用 `/api/clear`；
- `selectSession()` 只有后端成功后才更新 UI；当前“只加载历史但聊天仍写 runtime.session_id”的分裂状态必须清零；
- `shell_api.js` catch 分支禁止 `localActivate()`；`shell.js` 中同名旧 handler 一并删除，防脚本顺序变化后 fallback 复活；
- 编辑 active persona 不重建当前 `session_core`，响应返回 `applies_to_new_session=true`；历史会话继续使用持久化快照。

验收覆盖：正常切换新会话、取消、目标不存在、锁冲突、SQLite 事务失败、应用重建、历史会话恢复、事件流归属、
Auto 模式 session_id、API 失败旧人格继续生效，以及新建会话不再等价于清空。

## 10. OCEAN 编辑现状收口

本批不新增滑杆，但不能声称“没有 UI”。保留现有创建雷达与数字编辑作为兼容入口，并做三项收口：

- 前端只提交 `ocean`，展示 traits 使用后端派生结果；
- 编辑结果只影响后续新会话，当前会话保留创建时的人格快照；
- 非五标定点档位签名显示“自定义 OCEAN · 未验证”，默认不启用 P2 L1/L3。

开放调节批再决定未验证组合的连续参数包和上线 gate；P3 不把现有编辑控件当成已验证开放能力。五个冻结内置
预设从该入口“另存为”后才能编辑，避免原地改变 P4 标定对象。

## 11. 单对失败处置

选择“隐藏较弱者”，不创建“相近风格组”。合并会引入新产品实体、映射与盲判义务，超出 P3。

P4 某对失败后，比较两标定预设各自对 baseline 的多数票正确率与混淆矩阵召回，较低者标记
`hidden_after_pair_gate`；完全相同则按冻结顺序温柔、暴躁、甜美、可爱保留在前者。P4 verdict 未在场前只显示
“未验证”，不得预先隐藏。隐藏只作用于“已验证预设”入口，不隐藏或删除同档位签名的用户 persona，不改已有
会话快照和用户数据。

## 12. Fixture 重跑义务

P3 闭合门分三层：

1. CI 静态层：全部 `test_persona_constraint_*.py`，含 lint 正负控与 P1/P2 资产；
2. 受影响运行时层：persona repo/loader、memory recall、W2 expression、event types、arithmetic、plan final reply、
   desktop HTTP、缓冲式 L4 动作链与前端切换契约窄测；
3. 回退层：P1 三条关闭契约在真实接线后同 seed 逐字节一致，五人格各跑两次组装逐字节一致。

P1/P2 已冻结的 GGUF 96/338 轮原始实验不在 P3 重跑清单，保持不可变证据；真实模型组装矩阵与复制率复验归
P4。P3 不得用旧 artifact 代替新代码路径单测，也不得把静态 fixture 绿写成模型效果绿。

## 13. 分批执行与提交边界

1. **P3-0 阻塞锚**：L2 数值包、L3 机器语义、GenerationOptions 支持矩阵与 P4 归因臂先冻结；
2. **P3-A 派生/迁移/lint**：完整根 loader、20 边界、五预设入库、traits 导出迁移、API 旁路拒绝、lint 正负控；
3. **P3-B L1/L2/L3/L4 基线**：确定性选择、640 字符预算、参数应用 trace、显式信号、三事件生产消费、
   缓冲式 retry/fallback；
4. **P3-C 文案/UX**：15 条文案、persona 快照迁移、原子 session context、前端失败回滚、历史会话恢复；
5. **P3-D 闭合**：关闭契约、受影响 fixture 全量复跑、P3 报告与 v1.5 验收回填。

每批独立本地提交；用户未明确要求远端推送时禁止 `git push`。

## 14. P3 总验收行

- [ ] P3-0：L2 数据确认的数值包或 `no_effect_observed_within_preregistered_grid` 不采用裁决 + L3 机器效果已冻结，不存在未测全零、空转字段或未声明后端；
- [ ] P3-A：单一派生链、五标定预设、完整根解析、迁移三件套、traits 写旁路清零、lint 正控；
- [ ] P3-B：五标定点 L1/L2/L3 确定性组装、640 字符预算、三审计信号生产/消费、L4 基线动作链；
- [ ] P3-C：15 条文案、persona 持久化快照、真实新会话切换、失败零状态变化、历史会话 context 一致；
- [ ] 自定义 OCEAN 明示未验证且默认不启用约束，不删除用户现有向量；
- [ ] 单对失败隐藏策略实现但在 P4 verdict 前不生效；
- [ ] 关闭路径与无约束路径同 seed 逐字节一致；
- [ ] CI 静态层与受影响运行时层全绿；
- [ ] P3 报告明确：L2 applied-options、L3 档位、L4 direct/retry/fallback/observe trace 与模型效果待 P4。
