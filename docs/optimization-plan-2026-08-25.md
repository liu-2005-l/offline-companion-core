OC 优化计划 v6（2026-08-25：边界战役收尾 → 主线回归承接）
项目：Offline Companion · v1.6.0 开发中
日期：2026-08-25
定位：接替 optimization-plan-2026-08-23.md（v5）。v5 A/B/C/D/E 全闭合（D 全链 83f5ca9→b8a8911→8a1bd0c→5045645，E 全链 a4faceb→606959d→c191f30→607d7ad，998→1099），Batch E 红队矩阵已达 9/6/0（silent 清零）。本文后续承接主线回归 + v1.6.0 收尾路径
排序原则：清账 > 红队收尾 > 主线回归 > 收尾发布。不写时间估算
延续：v3 三原则（降级是底线不是目标 / 确定性算法工具化 / 无米之炊）+ v5 原则四（金路径≠可靠，边界不静默）全文继续适用，不重述

原则五（本阶段新增）：回归判据是用户视角全对率，不是用例数 passed
v5 Batch C 判决学到的最贵一课：result_rate=0.8（参数知识直出乘积 = 看似答对）假绿 vs full_success_rate=0.0（用户视角全对 = 答对 + 步骤对 + 审计过）真红——用例 passed 数和功能正确性是两件事。主线回归（6.1-6.6 的 209 用例 + 窗口布局 15 条）同样可能有"用例 passed 但功能不对"的假绿——比如 6.1 周期性事件提取的"提取了 N 个事件"passed，但事件语义是垃圾（提取了不该提取的）。

判据口径定死：主线每批用例完成 ≠ 验收通过。验收通过的三条同时满足：

用户视角端到端正确（输入到输出全程可复述给用户看）
边界不静默（原则四延续——边界输入要么正确执行要么明示降级）
观测可回答"为什么过"（从 B 批日志 + 事件流能回答这条用例为什么 pass，不是只看 passed 标记）
实操：每批用例完成后抽样 10% 跑端到端语义验证（不强制每条都跑，成本太高；但抽样不能为零——零抽样 = 默认假绿可能）。

基线口径更新（2026-08-27 开 6）：原 Phase 6 测试方案头部的 `816 passed / 880+` 是旧快照，W22 作废；当前验收基线改为 `1099 passed / 3 skipped` 不退步 + 新增用例全绿，终态数字以实跑为准。

embedding 依赖实情（2026-08-27 开 6）：生产路径当前使用 `shared.deterministic_embedding.embed_text(..., dimensions=768)` 的 deterministic hash-bow 近似，不是真 ONNX embedding。6.1 存储层可继续用固定 768 维向量验证；6.2 开工门禁已实测相似/不相似样本分布：similar `min=0.1438 max=0.6351 mean=0.3668`，dissimilar `min=0.1491 max=0.2864 mean=0.2094`，两组重叠，不能沿用真 embedding 口径的 `0.85/0.70` 语义阈值。分面后 literal_edit 为 `min=0.5017 max=0.6351 mean=0.5453`，paraphrase 为 `min=0.1438 max=0.4762 mean=0.3150`，因此 6.2 去重口径降级为 deterministic hash-bow 的字面近似去重，生产 duplicate 阈值落为 `0.50`；related `0.70` 当前没有生产链路消费者，标记为未实现/预留，不装作已生效。真语义 embedding 去重列入 v1.7.0 候选，避免 mock embedding 假绿。

理由：OC 是 C 端私人助理，第一优先级是可靠（嘉荣 USER.md 口径）。C 端用户不按判例说话，也不按用例清单说话——他们遇到的就是端到端的"帮我记一下"或"刚才那个再算一遍"。用例 passed 数是工程产物，用户视角全对才是产品判据。

Batch A｜清账批次（v5 E 段承接 + v5 终态对齐）
v5 E 方案已出稿（red-team-batch-e-design.md，15 判例七族三态判据 + E-0 前置 + E-1/E-2 分批），本文不重述。清账 = 把 E 开工前置答完 + v5 文档终态对齐，开工前逐项确认，已完成即跳过。

项	内容	确认方式
A-1	E-0 P-1 miss 可见性：no-hit / 放行轮次有无固定日志 anchor 行	跑任一词典外判例（如"按照MD5算法计算…"），看 R3/B4/B3 命中详情是否每轮固定输出。已解则 trace 一眼可答
A-2	E-0 P-2 日志级别：drill 会话开 debug（原始输出全文在 debug 级，B 批规格）	执行约定，记入 E-1 跑判例的会话协议
A-3	C-1 多轮历史可及层：指代"刚才的算法"能拿到上一轮约束实体	跑两轮构造（第一轮 booth 3×7 金路径绿，第二轮"再用刚才的算法算5乘8"），看会话历史可及性
A-4	C-2 反问通道：参数缺失时（“用booth算法算一下”）反问通道可达	跑判例，看是反问 / 明示降级 / 静默编参数哪一态
A-5	C-3 D-3 联测脚本化：D-3 五判例联测可重跑（预期值焙常量 + 规范校准行 0xCBF43926 锁 tests/test_algorithm_tools.py:64）	跑脚本一遍，三层断言（route/execute/transcribe）独立报失败
A-6	v5 终态对齐：v5 文档头部加状态标记（A/B/C/D 闭合 + E 方案出稿待开工 + 指向 v6），避免双活	本文档交付时同步改 v5 头
验收：六项全确认即本批闭合，无新代码。

Batch B｜E 红队执行（原则四的判据场）【已闭合：607d7ad / 1099】
承接 red-team-batch-e-design.md 的 E-1/E-2 分批。先测后判——预判不作为结论，以 B 日志 + D-3 事件层为准（v5 原文）。

B-1：E-1 侦察（跑矩阵出记档）
15 判例七族三态分类（correct / degraded-explicit / silent-fail），silent 清零是目标但不预设——侦察的产物是"边界现状全景记档"，不是"全绿报告"。

七族：负数（booth/gcd）/ 大数（77×88）/ 双工具链（booth→calculator）/ 参数缺失 / 多轮指代 / 降级链内容边界（MD5 编 32 位 hex = silent）/ 措辞变异（"为"族）。完整判例表见 red-team-batch-e-design.md，本文不重述。

侦察产物：每条判例的 trace 记档（输入 / 路由命中 / 工具执行 / 转述 / 最终输出 / 三态分类 / silent 时定位根因）。silent 清单 + 修复优先级排序。

B-2：E-2 修复（silent 清零 + 预置设计四条）
silent-fail 当批修。预置设计（red-team 方案已写，仅当实测触发启用）：

会话级约束记忆（多轮指代 E3 触发时，~10 行，只做"上一轮实体代入"不做完整指代消解系统）
trigger_keywords 扩展（裸意图路由缺口）
token 表语义族扩展（"为"族系动词，若 E6-2 实测放行）
内容审查入降级判据（降级明示不豁免编造内容——E5-1 MD5 编 32 位 hex 即使带了降级标记也是 silent）
本批不做（防蔓延，red-team 方案第 5 节）：意图泛化路由（"帮我排个序"无专名含参数 → quicksort 语义映射，记 v6 候选）；"为"族之外的系动词扩展；新工具扩容；E5-2 内容正确性（UTF-8 字节值对错不判，只判不伪装）；多轮约束记忆通用化。

闭合终态：E-1 侦察矩阵 6/3/6，E-2a 可见性推进到 6/6/3，E-2b 正确性推进到 9/6/0；silent 清零 + 全量 1099 passed / 3 skipped + D-3 drill + ruff 全绿，607d7ad 锁定。Batch B 闭合 = v5 原则四判据场收官。

Batch C｜主线 6.1-6.6 情感语义补全验证（方案已出）
docs/oc-refactor-phase6-test.md 的 209 用例方案执行。Phase 6 设计（docs/oc-refactor-phase6.md）：周期性事件提取（每 10 轮 LLM 提取 SemanticEvent）+ 三阶段召回（多路检索 RRF 融合 → 事件链 1 跳扩展 → 时序重组）+ 衰减遗忘（exp(-age/30d) × recall_boost，decay<0.1 且 recall_count==0 进 dormant）+ OCEAN 人格向量与情感联动。

按原则五验收——不靠用例数 passed，靠用户视角全对率：

子批	内容	用户视角判据
C-1	6.1 周期性事件提取	提取的事件语义可复述给用户看（不是"提取了 N 个"passed，是"提取的事件是用户会认同的语义单元"）
C-2	6.2 三阶段召回	召回结果对当前对话有相关性（不是"召回了 N 条"passed，是"召回的能在当前轮用上"）
C-3	6.3 衰减遗忘	30 天前的事件衰减、冷门事件进 dormant（不是"decay 函数跑了"passed，是"该忘的真的忘了"）
C-4	6.4 情感语义注入 prompt	注入后回复带情感连贯性（不是"prompt 含事件块"passed，是"回复读起来记得刚才聊过什么"）
C-5	6.5 OCEAN 人格向量	人格稳定 + 情感联动可观测（不是"向量有值"passed，是"同一输入在不同人格下回复风格可区分"）
C-6	6.6 端到端	用户视角全对率抽样 10% 跑端到端语义验证
假绿预判洞（原则五预置）：每子批用例 passed 后抽样跑端到端语义验证。抽样不能为零——零抽样 = 默认假绿可能。抽样发现假绿 → 该子批不算闭合，定位根因（用例只验"形态"不验"语义" = 用例本身要改，不是代码 bug）。

验收：六子批全过原则五三判据 + 全量回归绿。

6.1 闭合记录（2026-08-27）：当前属于“部分实现 + 补验证/补边界”状态，不是纯补验证也不是白纸实现。已补 W22 新基线、embedding 生产路径确认、语义事件向量 768 维 store fail-fast、同 ID 冲突传播测试、`vector_search returned ...` 与 `extracted ... events from turns X-Y` 两条日志 anchor；新增 `scripts/drill_phase6_1_semantic_events.py` 真链路抽样（真实 SQLite + deterministic `embed_text` 768 维 + 固定结构化后端，不加载模型），验证存储、去重、向量召回与日志 anchor。全量回归从 1099 推进到 1103。

6.2 门禁记录（2026-08-27）：新增 `fixtures/semantic_event_similarity_pairs.json`（40 similar / 40 dissimilar，similar 中同义改写覆盖 30%+，并以 `pair_type` 区分 `literal_edit` / `paraphrase` / `dissimilar`）与 `scripts/calibrate_phase6_2_hash_bow_thresholds.py`。校准不加载模型、不依赖 GGUF；结果显示 hash-bow 两组分布重叠，不能支撑真语义重复阈值，6.2 后续按字面近似去重推进，生产 duplicate 阈值为 `0.50`；同义改写双份存储是当前正确降级。related 阈值无生产消费者，第三组“相关不重复”判别对留到真正实现 related 链路时再补。

held-out 口径（2026-08-27）：三分面线性可分只是校准集内结论，不代表真实空间左尾；真实 literal_edit 低于 `0.50` 时按双份存储 + GC 兜底接受，paraphrase 高于 `0.50` 的误合并风险留到 v1.7 真 embedding 重校时复核。

6.3 开工锚点（2026-08-27）：语义事件召回三路当前为 vector（`EventRepository.vector_search` + hash-bow 768d query embedding）、bm25（外部注入路径；缺省为空时退回 `_lexical_ids`）、hash_bow（外部注入路径；缺省为空时退回 `_overlap_ids`，当前与 lexical 同源）。各路 top_k：vector 使用 `max(len(active_events), 1)`，bm25/hash_bow 由注入路径自行控制，缺省 lexical/overlap 返回全部有 token 交集的 active 事件；RRF 常数 `RRF_K=60`；融合后取调用方 `top_k`，related_events 显式 ID 一跳扩展在 RRF 之后执行，不参与融合分数。召回出口新增固定 anchor：三路返回数（含 0）、融合 top-K（id + rrf_score + 来源路标记）、query 摘要、后置扩展数与最终注入 ID，保证 no-hit 与最后一公里扩展可见。

6.3 hash-bow 连锁口径（2026-08-27）：vector 路与 lexical/hash_bow 路高度同质，当前不宣称“三路异构语义互补”。同义改写 query 召不回原事件时按 degraded 记档，不视为 bug；若 42 用例中语义召回项大面积 degraded，6.3 判决降级为词面召回口径，真语义召回列入 v1.7.0 候选。v1.7 真 embedding 另需复检 `PersonaSessionCore._assemble_context()` 每轮新建 `EventRecaller` + `embed_text(768)` 的注入点，避免模型实例每轮加载。

6.3 对表三分法（2026-08-27）：42 条 R/T 机械用例按当前实现拆分为“已实现有测试”全覆盖（R1-R42、T8-T11），其中新增显式覆盖 RRF rank=0、三路独立命中、no-hit anchor、related 一跳后置扩展、时序重组、召回统计、query expansion、中文情感标签与 `_assemble_context()` 真链路注入；“已实现缺验证”清零；“按 6.2 判决反转”单列为同义改写 query 语义召回，不归入机械 42 条 correct 门禁，预期为 degraded（召回空或召回近似词面事件均需靠 anchor 解释）。

6.4 开工口径（2026-08-29）：IdleThink 语义维护链路是纯写路径，`MemoryIdleHook` 只调用 `EventExtractor.extract()` 做残余补提取，并用 `should_gc()` / `mark_dormant()` 执行衰减 GC，不经过 `EventRecaller`，因此 6.2/6.3 的 hash-bow 召回判决不耦合本批 I/T 用例。二阶效应记档：hash-bow 召回弱会让词面冷事件 recall_count 长期为 0，从而更容易满足 `decay 低 + recall_count=0 → dormant`；v1.6 接受为检索层降级的下游表现，v1.7 真 embedding 生效后复核。

6.5 开工口径（2026-08-29）：召回注入敏感区使用 `docs/phase6-5-recall-injection-fixtures.md` 作为 fixture 事实源；当前物理载体是 LLM 请求的 `memory_block`，不是 `system_prompt` 字符串本体。U15/T19 复用 F1 词面命中对，U16 使用 F2 词面错开对与 F4 空库，U18 验证情绪上下文传入 `EventRecaller` 并影响候选入选；F2 未来是否翻转随 v1.7 R43-R46 判决。

6.5 边界口径（2026-08-29）：语义事件召回先按 `HASH_BOW_RECALL_THRESHOLD` 过滤，再做 emotion boost；情绪只重排已过阈候选，不捞起低于阈值的事件。`HASH_BOW_RECALL_THRESHOLD` 刻意同源于 `HASH_BOW_DUPLICATE_THRESHOLD`，共同表示当前 hash-bow 空间的“明确字面相似”带宽；v1.7 真 embedding 重校时随 R43-R46 一起复核。

6.5 免疫区口径（2026-08-29）：U1-U14 与 T16-T20 按确定性 API / prompt / 注入链路补齐；U19-U25 的当前前端闭合范围为记忆面板加载语义事件、类型筛选、空状态、删除与内容编辑接线，U22 手动新增语义事件与 importance 专项编辑仍由 API 覆盖，U25 的 100+ 分页/虚拟滚动列为 out of scope，不伪装成完整表单 UI。

6.6 开工口径（2026-08-29）：W10 只把显式 `related_events` 一跳扩展视为 correct，0.70 语义 related 自动关联未实现，按 degraded 记档并留 v1.7；W11/W13 沿用 6.2 判决后的 hash-bow 字面近似口径（`HASH_BOW_DUPLICATE_THRESHOLD = 0.50`），不再使用旧设计里的 0.85/0.75 真 embedding cosine。

Batch D｜窗口自适应布局（方案 v3 已定稿）
docs/window-adaptive-layout-design.md（v3，含实测数据归档）。三批次按依赖排序：

子批	内容	验收
D-1	批次 0 双监听修复（v1 评审抓出的 addEventListener 不覆盖 bug + data-layout/@media 双轨制）	双监听叠加不再现
D-2	批次 1 原生层（SetWindowPosW 直调物理像素 + webview.start() 前抢设 per-monitor DPI awareness PM_V1）	125%/150% DPI 实测归档，100% 隐身 case 验证
D-3	批次 2 前端档位（假最大化 + 物理像素坐标 + 多屏 MonitorFromWindow + GetMonitorInfoW.rcWork）	多屏不盖任务栏不超屏
与 C 可并行：6.1-6.6 在 core/情感层，窗口布局在 shell/原生层，分层不交叉。

验收：15 条已列 + 多屏 DPI 实测数据归档（依赖升版可复测翻案——TOOLS.md 沉淀的依赖库行为验证模式）。

Batch E｜v1.6.0 收尾发布
子批	内容	验收
E-1	全量回归绿 + 新基线 commit 锁定	全量 passed，无 skip 增加
E-2	文档同步（架构文档 v2.7 / CHANGELOG / README / 设计文档库终态头）	设计文档全部闭合终态头
E-3	版本号判定	嘉荣口径：完成已有 UI 后端接线 = patch（v1.6.x），新开能力 = minor（v1.7.0）。本批是 v1.6.0 收尾，判定走 patch 系列
验收：v1.6.0 发布就绪。

依赖图
Batch A（E 清账 + v5 终态对齐，已闭合）
   └─► Batch B（E-1 侦察 → E-2 修复，已闭合：9/6/0）
          └─► Batch C（6.1-6.6 验证，已解锁）
                 ├─► Batch D（窗口布局，与 C 可并行——分层不交叉）
                 └─► Batch E（v1.6.0 收尾，依赖 C+D 全绿）
                        └─► 下一计划候选（v1.7.0）
 
依赖理由：

A 先于 B：E-0 二项 + C-1/2/3 确认项是 E-1 侦察的前提（miss 可见性 / debug 级 / 多轮历史可及层不答就跑红队 = 每条判例变脏测试）
B 先于 C：E 红队的 silent 修复可能改 D 工具/B 观测，影响 C 的基线；E 闭合才有稳定基线开主线
C 与 D 并行：分层不交叉（core 情感层 vs shell 原生层）
E 依赖 C+D：v1.6.0 收尾要两者都绿
完成判据
主判据（原则五）：6.1-6.6 六子批过原则五三判据（用户视角端到端 / 边界不静默 / 观测可回答），抽样 10% 跑端到端语义验证无假绿
机制判据（原则四收官）：Batch B E 红队 silent 清零 + D 工具链生产路径稳定（已闭合：607d7ad / 1099）
数据判据：窗口布局多屏 DPI 实测归档（依赖升版可复测）
观测判据：主线用例的失败可从 B 日志 + 事件流回答"为什么过 / 为什么不过"
通用判据：全量回归绿 + 新基线 commit 锁定 + v1.6.0 发布就绪
下一计划候选（v1.7.0 方向，本文不立项）
P2-3 代码执行沙箱：词典外"按X算法"的通用解（模型生成代码 + 沙箱执行 + 测试验证）。v5 Batch C 数据已入（保守口径）：算法型代码生成（构造新中间状态）强负证据（步骤类 0%）；检索型生成（复述训练分布内模式）未测、本判决不适用。立项时判据设计必须区分这两类
plan-as-reasoning：已关闭（v5 Batch C 判决 full_success_rate=0.0，≤50% 分支，2026-08-24 入档）
P3 云轨路由：条件项，待云端配置（无云端是默认场景，嘉荣未配云端 API，所有兜底依赖本地构件）
v1.7.0 新能力候选（列清单不立项）：会话级约束记忆（如“再用刚才的算法”，E3 已 degraded 合格但体验仍弱）/ 扩展插件生态 / 移动端 / 多用户场景 / UI 自动化 Skill 上线商城——具体方向看 v1.6.0 发布后的用户反馈
非阻断顺手项（搭车）
v5 遗留照旧：decomposer 示例区多域分散 / 范例按钮读 candidate_sample_id / 警示块逐条排版与千分位百分号。v5 Batch B 搭车低优项"回复区算术校验 ✓ 标记"状态待确认——未做则降入本清单。

踩坑记录（本计划生成时的状态对齐教训）
状态对齐不能只信文档声明（v5 skill 踩坑记录原则重申）：v4.1 写着词典"与工具注册表同源"，实际 B4 词典含 CRC/MD5/RSA/SHA 而注册表只有 booth——已漂移。凡"同源/同步/一致"类声明，抽查实际数据源再采信
动状态档案前先读最新 daily（2026-08-25 本计划生成当晚实锤）：嘉荣发 D-3 进度后我隔了二十分钟给出的回复停在旧快照，把 5045645 已补齐的 Batch D 真闭合当"未闭合"改了一遍——同一根因两次发作。规则：长间隔/报告密集的晚上，回答或改状态类档案前必 read_daily 对齐最新 commit 链
验收行写进方案后不可移动（2026-08-25 双重实锤）：v5 D-3 验收行白纸黑字"日志可回答全部诊断问题"，drill 只跑行为面时我曾宣布"整批收口"并把缺口改名"E 前置"——缺口换个名字不等于闭合，这恰是帮 OC 消灭的假绿模式。本计划的完成判据行不允许在验收时移动
