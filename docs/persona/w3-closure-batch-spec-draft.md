W3 收口批规格（v0.2）
日期：2026-10-08
状态：v0.2。Q1–Q6 已裁决回填，冻结前阻断（C3-0）已吸收；TA 回报本文件落 repo 在场后即冻结。冻结后按 §3 顺序开工。
上游锚：W3 顺序裁决（2026-09-25）；P1 规格 b5ce47b + 勘误段 docs/w3-p1-output-gate-spec-draft.md:283（回源确认：仅"强化改挂 W3 收口批"一句，无目标清单）；因果表 v0.3；P2-1a 46ce3a3；P2-1b 85ece90；P2-2 终态报告 8d6cb4b；B-S09 修复 13ec263；runner 补强批 5cbe22e；p4-roster-kit.md:38/:106。
裁决 trace 事实（2026-10-08 23:17，全部 TA repo 实锚）：

校准边界 artifacts/persona_expression/w3_p2_repetition_calibration_v0_2.json:28/:53。
A/B 分叉真实位置 src/offline_companion/core/persona_session/session.py:824/:940/:1166；expression.py:41 仅为字段定义。
guard 默认值继承：scripts/run_persona_expression_w2.py:182（A/B 均继承默认）；scripts/run_w3_p2_repetition_retest.py:173（显式 true）。
终态产物 provenance 现状：scripts/run_persona_expression_w2.py:565、scripts/run_w3_p2_repetition_retest.py:517（矩阵仅记 commit）；.gitignore:60（checkpoint 被忽略）；scripts/persona_runner_audit.py:220/:517（sidecar 无 provenance、无 schema=1；provenance_schema=1 属 checkpoint 包装格式）。
v0.1→v0.2 变更：D1/C2a 终裁回填；R0 显式开关预检新增前置；C3-0 新增；C2b 降级 evidence-first audit；依赖图改串行；C1 判例面 5+1；v0.1 两处假绿声明修正；送达记档。

§0 冻结输入（今晚两轮 trace 汇总）
第一轮（23:05）：

A/B 开关未处理：P2-1a 未触碰；P2-1b 仅新增 cross_turn_repetition_guard_enabled 并明确锁定 A/B 继续在场（expression.py:41、test_persona_expression_w2.py:137、run_persona_expression_w2.py:182）。
重校分阶段解绑：R0 可立即、R1 受 p4-roster-kit.md:38（多轮人工判别）/:106（禁止 roster 前执行）阻断。
三臂口径修正：历史 baseline + 当前 A/B，w2_arm_c_retired 不恢复。
第二轮（23:17 裁决）：Q1 选 intent-aware（生产配置 0.09+gt）；Q2 选删除（分叉在 session.py）；Q3 有条件成立（R0 先于 C1/C2a）；Q4 声明不成立（W2 继承默认值，需显式钉死四组合）；Q5 :283 无目标清单（C2b 转 audit）；Q6 补 1 条生产默认集成判例。
冻结前阻断：矩阵不含完整 provenance、sidecar 无 provenance 无 schema、多 checkpoint 不可压成单一 run-level provenance → C3-0。

§1 挂账收拢总表
#	挂账项	挂账源	收口批归属
1	guard 上主干裁决（口径选型 + 默认值翻转）	P2-1b 裁决"上主干归 W3 收口"；P2-2 降级处置"guard enabled 随 W3 收口上主干"	C1
2	A/B 开关退役/删除 + 提醒强化（同一开关的两个挂账源）	P1 勘误 :283（“A/B 开关与提醒强化改挂 W3 收口批”）；W3-P1 规格"A/B 开关留 P2"	C2a + C2b
3	4-gram 红线 0.0368 重校	W2-F F4 裁决顺延；因果表对账 :77	C3/R0（立即）+ C4/R1（挂 P4 roster）
4	R1 去向域覆盖评估	因果表 R1（自称不一致→L4 域、提示泄漏→A3 lint 域）	C5
5	W3 收口报告 → 触发案例库批	案例库触发条件 = “W3 gate/报告/裁决闭合”	C6
6	终态产物 provenance 持久化（本轮新增）	TA 阻断：矩阵仅记 commit、checkpoint 被忽略、sidecar 无 provenance	C3-0
§2 批次拆解
C0 收口前置对表（docs-only）
本规格落 repo 锚定（冻结 commit）。
三臂口径落档：历史 baseline + 当前 A/B；w2_arm_c_retired 不恢复——C3/R0 产物与报告统一用此口径。
验收：docs-only commit，含 docs/README 导航更新。
R0 显式开关预检（C3/R0 前置，代码批）
背景（Q4 裁决）：W2 runner A/B 均继承 guard 默认值（run_persona_expression_w2.py:182），C1 翻转会把 W2 静默变 guard-on；P2-2 才是显式 true（run_w3_p2_repetition_retest.py:173）。
范围：R0 开跑前显式钉死四组合，消除对 config 默认值的隐式依赖——

W2 runner：A 臂 guard=false、B 臂 guard=false（显式传参，不继承）
P2-2 runner：A/B guard=true（显式，已是现状则仅加断言）
identity 提醒开关：两 runner 分别显式 false/true（与 guard 同构钉死）
判例：四组合显式传参断言（runner 启动期 config 快照与预期组合逐一比对，不匹配 fail-fast）。
验收行：R0 任一矩阵产物落盘前，其 runner 配置组合可从产物自身读出且与预检表一致；"W2=guard-off"由显式传参保证而非默认值巧合。
C3-0 终态审计产物（C3/R0 前置，代码批）
阻断事实：终态矩阵仅记 commit（run_persona_expression_w2.py:565、run_w3_p2_repetition_retest.py:517）；完整 provenance 只在被 .gitignore:60 忽略的 checkpoint 中；candidates sidecar 无 provenance、无 schema=1（provenance_schema=1 属 checkpoint 包装格式，persona_runner_audit.py:220/:517）。
方案（TA 设计）：扩展 sidecar 或新增 <matrix_stem>.audit.json——

归档每个 checkpoint 的 provenance 与 resume history（resume 链保留，多 checkpoint 不压成单一 run-level provenance）。
终态审计格式给独立 schema 版本（与 checkpoint 包装格式区分，独立演进）。
判例：多 checkpoint 场景下 audit.json 含逐 checkpoint provenance 段 + resume history 有序；单 checkpoint 场景等值；schema 号字段在场。
验收行：R0 产物在库后，仅凭 <matrix_stem>.audit.json（不依赖被忽略的 checkpoint）即可回答"这份矩阵是哪个 commit、什么配置、经历几次 resume 产出的"。
C3/R0 数据重算（立即执行段）
范围（TA 口径）：新矩阵跑批、candidate sidecar 固化、多轮分布计算、候选池与盲包预构建。P2-2 的 R0 可只跑 B 臂。
矩阵口径：W2 runner（A/B，guard 显式 false）+ P2-2 runner（B，guard 显式 true）——B 臂两态覆盖，与 C1 裁决解耦的前提由 R0 预检保证。
边界（冻结条款）：R0 不得宣称完成重校或移动红线；0.0368 总 gate 判据地位保留（因果表裁决 3）；A 臂产物带"当前代码 A，不可与 W2 A 历史归档对照"限定语。
产物措辞审查：C3 全部产物与报告出现"重校完成/红线已移动"字样即验收不合格。
依赖：R0 显式开关预检 + C3-0 完成后开跑；本次为 runner 补强批后首次全量生产级跑。

C1 guard 上主干裁决
D1 终裁（Q1）：intent-aware。

生产配置：threshold=0.09 + comparison="gt"（边界语义 0.0897435897，calibration_v0_2.json:28/:53；不得把 0.089744 截断值写成运行时常量）。
D2 默认值翻转：cross_turn_repetition_guard_enabled False→True。前置：R0 完成（顺序约束）+ B-S09 正控保持。
D3 复述不动：与 L4 共享出口重试预算边界维持 P2-1b 冻结（首轮同算、合并反馈、L4 失败优先走 L4 fallback）；P1 冻结面不碰（L4 语义域零进入）。
判例面（5+1，Q6 裁决）：五组默认路径判例（正常流/fallback 流/echo 场景/L4 联动/repetition 触发）+ 1 条生产默认集成判例——无显式 override 的 PersonaExpressionConfig() 默认开启 guard，已知 pair 按 0.09+gt 触发且 trace 对口。
明确不做：无需重跑整套 P2-1a 生成校准；保留现有 artifact/区间机械断言及 B-S09 正控。
验收行：默认 config 下 guard 生效且 0.09+gt 可从生产配置读出；五组路径 + 1 条集成判例全绿；A/B 对照限定语随 C2a 更新。
C2a A/B 开关删除（Q2 终裁：删除）
真实分叉位置：session.py（:824/:940/:1166）；expression.py:41 仅为字段定义。
删除面：

删除两个实验字段（A/B 臂开关字段）；
保留 config 类与 guard 字段；
style block 改为始终尝试组装；
身份提醒保留 is_identity_intent() 条件，仅移除开关前置；
辅助函数不删。
判例面：删除后 style block 组装无条件路径判例 + is_identity_intent 条件保持判例 + 四组合预检断言更新（A/B 维度消失后预检表收缩为 guard×identity 两维）。
验收行：expression.py/session.py 中 A/B 实验字段零残留（grep 级验收）；guard 字段与 config 类零 diff；R0 之后执行，不回溯改变 R0 产物语义。
C2b 提醒强化 audit（Q5 终裁：evidence-first audit）
:283 回源结果：原文仅"强化改挂 W3 收口批"，无目标清单。C2b 不得凭空立需求。
范围：

evidence-first audit：盘点当前输出面剩余红点证据（红线判例复检 + 生成面 spot check）；B-S09 已由 13ec263 解决，不重复立项。
无剩余红点与验收契约 → 以"无需进一步改动"闭合，记档归 C6。
有红点 → 红点逐条立验收契约后另立小批，不在本批扩权。
验收行：audit 结论三态（无需改动/红点清单+契约/移交 C5）落档，无第四态。
C5 R1 去向域覆盖评估
自称不一致 → L4 身份域：评估红线判例中自称不一致族是否在 L4 语义域清单内（缺覆盖不缺机制）。
提示泄漏 → A3 lint 机制泄漏域：13ec263 修复后评估正控是否进回归判例、lint 覆盖是否需扩。
结论三态：覆盖已足 / 扩判例 / 扩域（扩域 = 新批）。
验收行：评估报告 docs-only，两域各出三态结论 + 证据锚。
C4 R1 阈值裁决（挂起，等 P4 roster）
开工条件：P4 roster filled + R0 产物在库 + 判别协议从 p4-roster-kit 派生。
范围：人工自然度/容忍度判别映射为新红线、0.0368 正式移动（数值 gate 在 P4 矩阵后锚定——冻结设计一致）。
受 :38/:106 阻断，本批只立边界不执行。
C6 W3 收口报告
汇总 P1/P2/收口批终态；W3 原始输入对账：B 跨轮复读结构修复（P2 ✅）/ C 臂输出侧检测改造（P1 C 臂退役 ✅）/ 4-gram 重校（R0 ✅ + R1 挂 P4，诚实记"未完成"）。
报告闭合 → 触发案例库批（记忆链路三合一：profile 冲突检测 + 语义去重校准 + v1.8 embedding 复用验证）。
验收行：对账表逐条带锚点；未完成项明示"挂 P4 roster"不写成完成态。
§3 依赖与执行顺序（TA 裁决顺序）
C0（docs-only 锚定）
  → R0 显式开关预检（代码批，四组合钉死）
  → C3-0（audit.json 产物 + schema）
  → C3/R0 跑批（矩阵 + sidecar + 分布 + 盲包）
  → C1（D2 翻转 + 5+1 判例）
  → C2a（删除 + 预检表收缩）
  → C2b / C5（audit 与评估，可并行）
  → C6（收口报告 → 案例库批触发）
C4/R1：独立挂起等 P4 roster，不阻塞上述链路。
 
顺序硬约束：R0 严格先于 C1 翻转与 C2a 删除（否则 W2 guard 态或 A 臂数据被改变——Q3/Q4 裁决）；C2b/C5 在 C1/C2a 后做（评估对象含翻转后默认态）。

§4 冻结条款
R0/R1 边界：R0 产物与报告不得出现"重校完成/红线移动"；R1 才是阈值裁决主体。
三臂口径：历史 baseline + 当前 A/B；w2_arm_c_retired 不恢复。
输入/输出侧分工不翻案：v1_5:189 冻结条款维持，输出侧 remind_inject 整案否决不重开。
P1 冻结面不碰：L4 语义域零进入（guard 独立 decision/trace，仅共享出口点与重试预算）。
0.0368 双重地位：总 gate 闭合判据保留至 R1；不作为运行时阈值。
A 臂限定语：当前 A 臂数据与 W2 A 历史归档不可对照；C2a 删除后转"历史结论"。
校准常量纪律：生产配置 threshold=0.09 + comparison=“gt”；0.0897435897 为边界语义值，禁止截断常量入库。
四组合显式钉死：R0 及之后一切 runner 跑批的 guard/identity 态由显式传参保证，禁止依赖 config 默认值（C1 翻转后 W2 口径不受影响）。
终态产物 provenance：以 C3-0 独立 schema 的审计产物为准；"矩阵含 provenance"类声明在 C3-0 落地前不得出现。
§5 裁决记录（2026-10-08 23:17）
问题	裁决	关键证据
Q1 校准口径	intent-aware；threshold=0.09+gt	calibration_v0_2.json:28/:53
Q2 A/B 开关	删除；分叉在 session.py 非 expression.py	session.py:824/:940/:1166
Q3 R0 解耦	有条件成立；R0 先于 C1/C2a	顺序约束
Q4 runner 开关声明	不成立；W2 继承默认值	run_persona_expression_w2.py:182、run_w3_p2_repetition_retest.py:173
Q5 :283 回源	无目标清单；C2b 转 evidence-first audit	docs/w3-p1-output-gate-spec-draft.md:283
Q6 判例面	补 1 条生产默认集成判例	PersonaExpressionConfig() 默认态
阻断×3	C3-0 吸收	runner :565/:517、.gitignore:60、persona_runner_audit.py:220/:517
§6 送达记档
v0.1（2026-10-08 23:05 前后 send_file）回执成功但未落 TA repo——"方案已出 ≠ 对方已有"第四次发作。按纪律不重发旧版，Q1–Q6 裁决直接升进本版。冻结动作以 TA 回报本文件落 repo 在场为前置。
