OC 拟人表述升级设计
版本：v2.1（§8 四锚已确认，落设计决策）
状态：方案待评审
基准：Offline Companion v1.8.0（tag 1084c13）真实架构
需求来源：外部参考文档（仅取目标形态与设计原则，技术落点全部废弃重写）
对齐方法论：V1 semantic embedding 批——先钉判据 → baseline 测量 → 实现 → 度量验证 + 盲评终裁

0. 定位声明
本批目标：让助手输出从"工具式答复"转向"陪伴式对话"，度量可验收，不引入新模型依赖，全功能可一键回退。

与参考文档的关系：参考文档的"新建平行拟人化系统"形态不采纳。OC 的拟人化原材料已齐——OCEAN 人格向量、情感模块（Phase 6 全闭合）、语义记忆召回（v1.8.0）、persona 资产、身份锁（6.5 关账）。本批 = 少量新建 + 大量接线。

1. 资产盘点（决定什么是接线、什么是新建）
既有资产	现状	本批用法
OCEAN 人格向量	persona 资产内，active_persona_id 每轮生效	映射为风格参数包（W3）
emotion 注入	emotion 进语义召回 session.py:381；OCEAN tone + emotion instruction :391/:400（组装顺序末位）	语气调制输入源 + W3 扩展点，不新建情绪分类
语义记忆召回	EventRecaller，_assemble_context() session.py:354 + v1.8.0 embedding，paraphrase 29/31 零 FP	织入句式升级（W4）
reformat_local_reply	非流式 conversation_orchestrator.py:482，流式 :557	polisher 之后执行的结构化整形层，本批不动它
persona 存储	YAML（configs/personas/default.yaml + persona_loader.py:16）/ DB schema（engine.py:330：ocean_json、traits_json、anchor、system_prompt、raw_json）/ UI（persona_repo.py:135、:189）	raw_json 搭载 style_examples（§3.1），无 schema 迁移
system_prompt_locked 身份锁	6.5 关账：display_name 从 latest_profile_memory() 读，conn-aware	分层不动：身份归锁，风格归本批（W2）
semantic_extractor → decision_engine → MemoryStoreController	偏好提取既有链路	偏好记忆走此链，不建 KV（W3）
SSE 切片流	前端 gap repair 有跨轮重放前科（postmortem 在档）	渲染节奏化的 seq 审查依据（W4）
M1/M2/M3 算术审计	已闭合（事故五），任务侧	兼容规格的保护对象（W5 复测）
C-1~C-6 后置校验链	任务执行侧全闭合	任务能力回归判据来源（W2/W5）
Waitress threads=4	单用户桌面宿主	节奏化必须落前端的依据（W4）
组装顺序（TA 确认）：记忆/语义事件召回 → combined_memory_block → system_prompt_locked → 算术提示/Skill prompt → OCEAN tone + emotion instruction（:391/:400）。行号以 repo 为准（v2 档案期 :368 系 6.5 时代旧锚，已漂移）。

2. 设计原则
验证而非信任（OC 既有哲学，本批的特殊应用）：不用规则改写碰文本语义。后置层只做零语义风险变换，风格生成主力在 Prompt 层；
算术保护不变量（采自参考文档，本批核心规格）：数字、公式、断言块、警示块、代码块绝对原样，润色层对保护区逐字节透传；
宁平勿尬：共情、语气调制只在高置信度触发，不确定保持中性礼貌；
可开关回退：全功能一键关闭，关闭后输出与现状逐字节一致（可测的确定性验收行）；
1.5B 单轨验收：无云端是默认场景，所有效果验收在本地 1.5B 轨完成；
1.5B 有效杠杆序：few-shot 示例模仿 > 抽象风格指令（GBNF 批同构结论：结构硬约束 > prompt 软提醒）；解码参数 > prompt 调整 > 后置处理。
3. 架构
3.1 三层杠杆（按有效性排序）
第一层 Prompt 生成侧（主力，W2）

few-shot 风格锚点：persona 资产挂 3-5 轮目标风格示例对话。挂载方式（锚 3 确认后决策）：style_examples 走 raw_json 搭载——YAML persona 写 style_examples 字段，raw_json 天然保留未知字段，消费侧显式读取 persona.raw_json.style_examples 注入；无 schema 迁移、无 DB 变更。UI 创建/编辑人格的 style_examples 支持本批 out of scope（default + YAML persona 先行）。注入位置：prompt_parts 追加独立 style block（组装顺序末位附近，与 tone instruction 相邻），不触碰 system_prompt_locked（锚 4 分层确认：身份归锁 :220/:224/:232，风格归本批）；
解码参数包：persona 级 temperature / top-p / repetition_penalty 预设，默认 persona 用保守预设。零成本，W2 首先单独 A/B；
织入指令：prompt 层指令"将召回记忆自然融入回复，不要列表复述"。生成侧效果靠 W2 判据验证，不预设有效。
第二层 接线复用（W3）

偏好记忆：走 semantic_extractor → decision_engine → MemoryStoreController 既有链，新 memory_type（user_preference 类），进 FTS + embedding 召回，享受 Supersede/迁移/清理全生命周期。不建 KV 存储；
情绪→语气：emotion_context 已在注入链上（:381 进语义召回 + :400 emotion instruction），本批只消费它（置信度高→语气调制，低→中性），不新建情绪分类器。注意与既有 tone/emotion instruction（:391/:400）的指令冗余审查——W3 是扩展该 block 而非另起注入点，避免两段风格指令互相稀释；
OCEAN→风格参数包：查表纯函数，5 维 × 3 档（高/中/低），不做组合爆炸、不做运行时动态调整。参数包影响两处：prompt 锚点选择 + 后置层档位。
第三层 零语义风险后置层（W4，新建 persona_polisher.py）

纯函数、零依赖、可插拔，接入 assemble_reply 内、算术审计之后、return 之前。

插入点规格（锚 2 确认后锁定）：

开关跟随既有 flag 惯例：assemble_reply 新增 polish_enabled 参数，与 memory_enabled / audit_arithmetic 同型（auto_turn_orchestrator.py:119/:142 既有先例）。对话路径 True；Auto 任务转述路径显式传 False——任务输出不经润色，"任务输出保护"问题就此消灭，不需要 W4 单独规格化一套保护机制；
reformat_local_reply（:482 非流式 / :557 流式）在 polisher 之后执行，本批不动它——polisher 产出经它结构化整形，顺序天然安全；
流式路径（:539 → :557）：当前架构是生成完成再切片 SSE，polisher 在切片前对完整文本生效，两条路径同点覆盖；
前向兼容注记：候选池"SSE 真流"落地后，完整文本不再存在于切片前——polisher 届时必须移位（prompt 层-only 降级或分块边界感知模式）。真流批开工前以本节为前置审查项。
只做三类变换：

消息拆分：按语义单元（句号/问号/感叹号/转折词边界），逐字节保留原文，保护区（断言块/代码块/警示块）整块不拆；
动作标签：句外纯追加（如"[歪头]"），触发源用 decision_engine 意图分类结果而非裸关键词表（防措辞变异），默认低频档；
逐字节透传：保护区内容原样通过，含"数字+运算符"任何形态。
不做：文本口语化改写、缩略语替换、语气词插入进句内。理由：改写动作会摧毁保护正则赖以匹配的文本形态（参考文档 3.2.1 的例句"×"被改"乘"即自证），且规则碰语义的责任边界与"验证而非信任"冲突。

3.2 节奏化表现层（W4，前端落点，写死）
后端 SSE 切片流不动。前端缓冲 chunk 后按节奏逐字渲染 + "正在输入"状态机。

落点必须是前端的依据：Waitress threads=4，后端 sleep 调速会占住 worker；且 SSE gap repair 有跨轮重放前科，后端节奏化必然引入新中断语义，seq 基线交互必须过一轮审查——前端方案天然绕开这两条。

打断兼容（可选）：若做，中断时的 seq 语义先出审查小节再实现，默认不做。

3.3 主动追问（W4 尾部，默认关闭）
默认关闭。触发条件 = decision_engine 判定闲聊信号 × 频率控制（每会话至多 1 次），不掷概率骰。需与 IdleThink 主动行为层做叠加审查（两层"主动"不可同轮并发触发）。

4. 批次
W1 判据批（先决，不测 baseline 后面全是感觉之争）
判例集预注册进 repo：场景分布（闲聊 40% / 任务 40% / 混合 20%）× 轮次深度（单轮 / 3 轮 / 15 轮连续），40 条，出题分布表先于实现落档；
六指标规格化（计算脚本放 scripts/ 或 tests/，dev 侧，不进 B 层运行时——B 层计算白名单不扩）：
开场多样性：回复前两词 distinct-2
句长方差：句长 CV
列表依赖率：bullet/编号结构回合占比（按场景分层统计）
模板短语密度：黑名单（“作为一个AI”“总的来说”"我建议"等）命中率/千字
口语标记密度：语气词与口语词密度，双向指标（过高 = 油腻，同样扣分）
跨轮结构雷同：相邻轮次回复 n-gram 重叠度
baseline 测量：现状跑判例集，六指标 + 全部落档；
50 轮人设漂移 probe：连续 50 轮，每 10 轮 probe 身份关键词保持度 + 语气指标带漂移。1.5B 长对话漂移率实测——P0 风险定级（参考文档标"极低"）由本 probe 翻案或翻车。
W2 锚点批（Prompt 主力）
解码参数包 A/B（零成本先试）；
风格锚点语料编写 + persona 挂载 + 注入；
任务能力回归闸门：C2 判据 + 既有任务路径用例，锚点注入（+200~400 token）前后对比，任务能力不得掉线。这是本批最大技术风险（1.5B 上下文预算挤占），A/B 不通过则锚点减半重测；
TA 盲评 A/B：同判例子集，有/无锚点两版盲读。
W3 接线批
偏好 memory_type + 提取规则（复用 semantic_extractor 框架）；
emotion_context 消费侧语气调制（置信度阈值 + 宁平勿尬）；
OCEAN 查表 + 参数包双落点（prompt 侧 + 后置档位侧）。
W4 表现批
persona_polisher：拆分（语义单元）+ 标签（意图触发）+ 透传；polish_enabled flag 落地（Auto 路径 :142 显式 False）；
前端渲染节奏化 + 输入状态机（seq 语义审查小节先行）；
记忆织入双路径：注入模板自然化（确定性收益，先行）+ 生成侧融入指令（W2 已验，视效果取舍）；
主动追问（默认关闭实现）。
W5 收口批
算术兼容复测：事故五原用例全过 + 新增"润色后保护区逐字节一致"断言；
开关回退回归：关闭后全判例集输出与现状逐字节一致；
六指标复测 vs baseline + 判例集盲评终裁（指标全绿但盲评无感 → 推翻指标权重，人终裁）；
C 链语义任务回归 + tripwire 钉桩 + 文档收口。
5. 验收标准（预注册形态）
算术兼容：事故五原用例复测通过，保护区逐字节一致断言通过；
回退性：开关关闭，判例集输出与现状逐字节一致；
任务能力：C2 + 任务路径回归零掉线（token 挤占不伤能力为硬闸门）；
效果：六指标相对 baseline 改善方向符合预注册预期 + TA 盲评优于此 baseline（具体数字 W1 baseline 出来后定，不在方案期拍）；
漂移：50 轮 probe 身份关键词零丢失，语气指标不出基线带；
性能：后置层单轮 < 100ms；节奏化不增加后端延迟。
6. 风险表
风险	等级	缓解
token 挤占伤任务能力	高	W2 A/B 硬闸门，不过则锚点减半
1.5B 人设漂移	严重（W1-B.1）	W1-B.1 受控重跑：N=5 漂移率 5/5，主要断崖在 P50 性格/自述题；锚点示例必须含 in-persona honesty 与身份纠偏样本
盲评无感（指标假绿）	中	人终裁优先于指标
语气调制油腻	中	口语标记双向指标 + 宁平勿尬阈值
前端节奏化碰 SSE seq 语义	中	seq 审查小节先行，默认缓冲不改流
7. 非目标
语音、3D 形象、深度心理疏导、错字模拟、用户风格自适应学习（候选池另议）、云端风格差异适配。

8. 锚点确认记录（2026-08-30 TA 确认，v2.1 落档）
组装顺序（session.py:354 _assemble_context）：召回 → combined_memory_block → system_prompt_locked → 算术提示/Skill prompt → OCEAN tone + emotion instruction（:369/:391/:400）。→ 决策：style block 追加在 prompt_parts 末位附近；档案期 :368 系旧行号，emotion 进语义召回实际在 :381；
任务路径：Auto 任务转述走 assemble_reply（auto_turn_orchestrator.py:119/:142），memory_enabled=False 且 audit_arithmetic=False。→ 决策：polish_enabled 同型 flag，Auto 路径显式 False，任务输出保护内生于开关设计；
persona 存储：YAML（default.yaml:21 / persona_loader.py:16）+ DB schema（engine.py:330，含 raw_json）+ UI（persona_repo.py:135/:189），无 style examples 专用字段。→ 决策：raw_json 搭载 + 消费侧显式读取；UI 编辑 out of scope 本批；
身份锁分层：锁入口 :220，conn-aware 自称解析 :224，返回自称 + persona.system_prompt :232；types.py:400 声明 name 非自称。→ 决策：身份归锁不扩权，风格走独立 style block，分层成立。
遗留待确认一项：UI 创建人格（persona_repo.py:135/:189）的 raw_json 写入路径是否透传未知字段——不影响本批范围（UI out of scope），只影响未来 UI 支持时的前置条件，W2 开工时顺带确认即可。

9. 版本落点建议
新能力面，建议 v1.9.0（对齐"完成新能力 = minor"口径）。批内先出 W1，W1 数据决定 W2 锚点规模与漂移对策。
