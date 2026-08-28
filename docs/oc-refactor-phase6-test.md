Phase 6.1-6.6 全量验证方案
目标：验证情感语义补全全链路——事件提取 → 存储 → 召回 → 闲时维护 → UI 管理 → 端到端集成
基线：1099 passed, 3 skipped（2026-08-27 开 6 口径；不得退步）
预期终态：1099 不退步 + 新增用例全绿（终态数字以实跑为准）

一、6.1 SemanticEvent + 存储层
单元测试
#	用例	预期
S1	store + get → 字段完整	16 个字段全部正确读回
S2	store 无 embedding → get	content_embedding=None
S3	store 有 embedding → vector_search	返回 (event, distance) 列表
S4	store 后 mark_superseded → get_active	不返回该事件
S5	store 后 mark_dormant → get_active	不返回该事件
S6	update_recall_stats → get	recall_count +1, last_recalled_at > 0
S7	get_active 默认按 importance DESC	importance=5 排在 importance=2 前面
S8	get_by_type(“fact”)	只返回 event_type=“fact”
S9	get_by_type(“fact”) 当有 fact + preference	只返回 fact
S10	get_recent(days=30)	只返回 30 天内创建的
S11	get_recent(days=0)	返回空列表（截止时间已过）
S12	store 100 条 → get_active(limit=50)	返回 50 条，按 importance DESC
S13	store 同 event_id 两次	第二次 INSERT 失败（PRIMARY KEY 冲突，仓储层不吞错）
S14	vector_search 空库	返回空列表
S15	vector_search top_k=5 但库里有 20 条	返回 5 条
S16	get 不存在的 event_id	返回 None
衰减算法测试
#	用例	预期
D1	新事件 importance=5, age=0	decay_score ≈ 5.0（exp(0)=1）
D2	30 天前事件 importance=5	decay_score ≈ 5 × exp(-1) ≈ 1.84
D3	90 天前事件 importance=1	decay_score ≈ 1 × exp(-3) ≈ 0.05
D4	recall_count=10 → recall_boost	min(1+10×0.1, 2.0) = 2.0（上限）
D5	recall_count=5 → recall_boost	1+5×0.1 = 1.5
D6	should_gc：decay=0.05, recall_count=0	True
D7	should_gc：decay=0.05, recall_count=1	False（有被召回过）
D8	should_gc：decay=0.5, recall_count=0	False（分数还不够低）
D9	importance=0 → decay_score=0 → should_gc True（如果 recall_count=0）	True
D10	half_life=60 天 vs 默认 30 天 → 同一事件 decay_score 更高	60 天半衰期分数 > 30 天
边界测试
#	用例	预期
B1	content 为空字符串	不崩，存储成功（内容校验在提取层）
B2	emotional_valence=-1.0, emotional_arousal=1.0	存储成功，取回值正确
B3	source_turns=[]	存储成功，json.dumps(“[]”)
B4	related_events 有 3 个 ID	JSON 数组正确序列化/反序列化
B5	content_embedding 维度 != 768	vector_search 报错或返回空（看 sqlite-vec 行为）
B6	temporal_marker 为空字符串	存储成功，默认值 “”
trace 验证
#	操作	预期
T1	手动改 DB 把 status 从 active 改成 invalid 值	get_active 不返回该事件（status != ‘active’）
T2	删除 semantic_events_vec 虚拟表 → vector_search	报错或返回空，不静默成功
T3	store 后不 commit → 另一个连接 get	返回 None（未提交）
二、6.2 事件提取器
校准口径（2026-08-27）：生产 embedding 是 deterministic hash-bow 768 维，不是真 ONNX embedding。`fixtures/semantic_event_similarity_pairs.json` 40 组相似 + 40 组不相似判别对实测：similar `min=0.1438 max=0.6351 mean=0.3668`，dissimilar `min=0.1491 max=0.2864 mean=0.2094`，分布重叠严重；`pair_type` 分面用于区分 `literal_edit` / `paraphrase` / `dissimilar`，其中 literal_edit `min=0.5017 max=0.6351 mean=0.5453`，paraphrase `min=0.1438 max=0.4762 mean=0.3150`。因此 6.2 去重验收降级为“字面近似去重”口径，生产 duplicate 阈值为 `0.50`；同义改写双份存储是正确降级。related `0.70` 当前没有生产链路消费者，标为未实现/预留；真语义同义改写去重列入 v1.7.0 真 embedding 候选。
触发逻辑
#	用例	预期
E1	should_extract(turn=10)	True
E2	should_extract(turn=9)	False
E3	should_extract(turn=20)	True
E4	should_extract(turn=0)	False
E5	should_extract(turn=10, interval=10)	True
E6	should_extract(turn=15, interval=10)	False
提取正确性
#	用例	预期
E7	正常对话（含事实信息）→ extract	返回事件列表，event_type 正确
E8	纯闲聊（“你好”“今天天气不错”）→ extract	返回空列表
E9	含多个事件的对话 → extract	返回多个事件
E10	提取的事件有 emotional_valence	-1.0 ~ 1.0 范围内
E11	提取的事件有 emotional_arousal	0.0 ~ 1.0 范围内
E12	提取的事件有 importance	0.0 ~ 5.0 范围内
E13	提取的事件有 temporal_marker	格式 “session:{sid}:turn:{start}-{end}”
E14	提取的事件有 source_turns	列表长度 = end - start + 1
E15	提取的事件有 content_embedding	768 维
去重逻辑
#	用例	预期
E16	新事件，库无相似 → _should_store	True
E17	新事件，库有字面近似重复匹配（hash-bow cosine >= 0.50），新事件 importance 更高	True + 旧事件被 mark_superseded
E18	新事件，库有字面近似重复匹配（hash-bow cosine >= 0.50），旧事件 importance 更高	False（跳过）
E19	新事件，库有字面近似重复匹配（hash-bow cosine >= 0.50），importance 相同	False（保留旧的）
E20	新事件与旧事件为同义改写但不达字面近似重复	True（双份存储；merge/related 语义阈值未实现）
E21	新事件和旧事件无字面近似相关	True
E22	新事件和旧事件 embedding 都为 None	True（无向量可比时默认存储）
E23	库为空 → _should_store	True
E24	_merge_events 后旧事件 content	“旧内容；新内容”
E25	_merge_events 后旧事件 importance	max(旧, 新)
E26	_merge_events 后旧事件 valence	(旧 + 新) / 2
E27	_merge_events 后旧事件 arousal	max(旧, 新)
E28	_merge_events 后旧事件 related_events	包含新事件 ID
LLM 容错
#	用例	预期
E29	LLM 返回 markdown 包裹的 JSON（json [...] ）	正确解析
E30	LLM 返回非 JSON 文本	返回空列表，不崩
E31	LLM 返回空字符串	返回空列表
E32	LLM 返回 JSON 但字段缺失（无 importance）	用默认值 1.0
E33	LLM 返回 JSON 但 event_type 不在 6 种内	跳过该事件或标记为 “fact”
E34	LLM 超时	返回空列表，不崩（或抛出由调用层处理）
cosine_similarity 工具
#	用例	预期
E35	相同向量	1.0
E36	正交向量	0.0
E37	相反向量	-1.0
E38	维度不匹配	抛 ValueError
E39	零向量	返回 0.0
trace 验证
#	操作	预期
T4	mock LLM 返回已知事件 → extract → 查 DB	DB 有且仅有该事件
T5	mock LLM 返回与已有事件 hash-bow cosine >= 0.50 的字面近似事件 → extract	DB 不新增，旧事件不变
T6	mock LLM 返回同义改写但 hash-bow cosine < 0.50 的事件 → extract	DB 新增事件（字面近似口径下不 merge）
T7	mock LLM 返回无关事件 → extract	DB 新增事件
三、6.3 三阶段召回算法
Stage 1：多路检索
#	用例	预期
R1	recall 空库	返回空列表
R2	recall 有数据 → 向量路返回结果	vector 路有 candidate
R3	recall 有数据 → BM25 路返回结果	bm25 路有 candidate
R4	recall 有数据 → hash-bow 路返回结果	hash_bow 路有 candidate
R5	三路返回同一事件 → RRF 融合后该事件分数最高	1/(k+0) × 3
R6	事件只在一路出现 → RRF 分数 = 1/(k+rank)	单路分数
R7	事件在两路出现 rank=0, rank=1 → 分数 = 1/60 + 1/61	≈ 0.033
RRF 融合
#	用例	预期
R8	三路 rank=0 同一事件	RRF 分数 = 3/60 = 0.05
R9	向量 rank=0, BM25 rank=2, bow 无	分数 = 1/60 + 1/62
R10	k=60 vs k=10 → k=10 时 rank 差异影响更大	k=10 排序更陡峭
R11	空 candidates → _rrf_fuse	返回空 dict
情感维度 boost
#	用例	预期
R12	emotional_context={valence:0.8, arousal:0.8} + 事件 valence=0.8, arousal=0.8	emotional_sim=1.0, boost ×1.3
R13	emotional_context={valence:-0.8, arousal:0.8} + 事件 valence=0.8, arousal=0.8	emotional_sim 较低, boost < 1.1
R14	emotional_context=None	无 boost
R15	事件 valence=0, arousal=0 + context valence=0, arousal=0.5	emotional_sim ≈ 0.5
R16	_emotional_similarity 完全匹配	1.0
R17	_emotional_similarity 完全相反	0.0
衰减权重
#	用例	预期
R18	新事件 importance=5 vs 旧事件 importance=5 → 同分 RRF	新事件最终分数更高（decay 加权）
R19	旧事件 importance=5 recall_count=10 vs 新事件 importance=1 recall_count=0	旧事件可能分数更高（recall_boost=2.0）
R20	decay_score=0 → rrf_score × 0.5	衰减事件被降权但不排除
Stage 2：事件链扩展
#	用例	预期
R21	top_event 有 related_events=[“e2”]，e2 importance=4, status=active	e2 在结果中
R22	top_event 有 related_events=[“e2”]，e2 importance=2	e2 不在结果中（< 3.0）
R23	top_event 有 related_events=[“e2”]，e2 status=dormant	e2 不在结果中
R24	top_event 有 related_events=[“e2”,“e3”]，两个都 importance≥3	e2 和 e3 都在结果中
R25	top_event 有 related_events=[“e2”]，e2 已在 top_events 中	不重复添加
R26	top_event.related_events=[]	无扩展
R27	related_event 又有 related_events=[“e3”]（2跳）	e3 不扩展（chain_depth=1 只做1跳）
Stage 3：时序重组
#	用例	预期
R28	事件 A created_at=100, B created_at=200, C created_at=50	结果顺序 [C, A, B]
R29	事件 created_at 相同	保持稳定排序（不崩）
R30	召回结果为空	返回空列表
召回统计
#	用例	预期
R31	recall 后 recall_count +1	所有返回的事件 recall_count 都加 1
R32	recall 后 last_recalled_at 更新	last_recalled_at > 旧值
R33	同一事件在 top_events 和 expanded 中都有	recall_count 只 +1（不重复计数）
Query Expansion
#	用例	预期
R34	LLM 可用 → _expand_query 返回 3 个变体	queries = [原始, 变体1, 变体2]
R35	LLM 返回空行 → _expand_query	返回空列表，只用原始查询
R36	LLM 不可用（None）→ recall	只用原始查询，不崩
R37	hash-bow 用 4 个查询联合检索	bow_results 长度 ≥ 单查询结果
格式化
#	用例	预期
R38	format_event_narrative 空列表	返回空字符串
R39	format_event_narrative 有事件	返回带时间戳和类型的文本
R40	事件 emotional_valence=0, arousal=0	无情感标注
R41	事件 emotional_valence=0.8, arousal=0.7	有"（积极, 激动）"标注
R42	事件 emotional_valence=-0.5, arousal=0.3	有"（消极, 平静）"标注
trace 验证
#	操作	预期
T8	灌入 e1(related to e2) → recall 查询命中 e1 → 结果包含 e2	事件链扩展生效
T9	灌入 e1(高 importance) + e2(低 importance) → recall → e1 在前	RRF + decay 排序正确
T10	灌入旧事件(90天前) + 新事件(今天) → recall 同查 → 新事件在前	衰减权重生效
T11	emotional_context={valence:0.9} + 事件 valence=0.9 → recall vs 无 context → 有 context 时该事件排名更高	情感 boost 生效
四、6.4 IdleThink 集成
残余消息补提取
#	用例	预期
I1	上次提取在 turn 10，当前 turn 17 → on_idle	补提取 turn 11-17
I2	上次提取在 turn 10，当前 turn 20 → on_idle	不补提取（已到 20，走正常提取）
I3	上次提取在 turn 10，当前 turn 10 → on_idle	不补提取（无残余）
I4	从未提取过，当前 turn 7 → on_idle	补提取 turn 1-7
I5	当前 turn 0 → on_idle	不提取
衰减 GC
#	用例	预期
I6	事件 decay_score=0.05, recall_count=0 → on_idle	被标记 dormant
I7	事件 decay_score=0.05, recall_count=1 → on_idle	不被标记（有被召回）
I8	事件 decay_score=0.5, recall_count=0 → on_idle	不被标记（分数不够低）
I9	库无 dormant 候选 → on_idle	gc_count=0
I10	库有 10 条 dormant 候选 → on_idle	gc_count=10，全部 mark_dormant
I11	已 dormant 的事件 → on_idle	不重复处理
触发条件
#	用例	预期
I12	idle_duration=300 → on_idle	执行
I13	idle_duration=299 → on_idle	不执行（未到阈值）
I14	idle_duration=600 → on_idle	执行
I15	on_idle 无残余 + 无 GC	返回空 actions 列表
I16	on_idle 有残余 + 有 GC	返回 2 条 action 描述
trace 验证
#	操作	预期
T12	手动改 last_extracted_turn → on_idle	补提取的 turn_range 正确
T13	手动改事件 created_at 为 100 天前 → on_idle	该事件被标记 dormant
T14	on_idle 执行后查 DB → dormant 事件的 status	status=“dormant”
T15	IdleThink 注册 memory_maintenance hook → 闲时触发	on_idle 被调用
五、6.5 记忆管理 UI + 召回注入
API 测试
#	用例	预期
U1	GET /api/memory/events → 返回 active 事件列表	200, JSON array
U2	GET /api/memory/events?type=fact → 只返回 fact	200, 只含 fact 类型
U3	GET /api/memory/events?type=invalid →	200 返回空列表 或 400 参数错误
U4	POST /api/memory/events → 创建事件	201, 返回 event_id
U5	POST 创建的事件有 content_embedding	embedding 非空
U6	DELETE /api/memory/events/{id} → mark_dormant	200, status=“dormant”
U7	DELETE 不存在的 event_id	404
U8	PATCH /api/memory/events/{id} → 更新字段	200, 字段更新
U9	PATCH 不存在的 event_id	404
U10	GET 空库	200, []
system_prompt_locked 覆盖修复
#	用例	预期
U11	有 profile_memory（display_name=“小诺”）→ assemble_reply	system_prompt 中 {display_name} 被替换
U12	无 profile_memory → assemble_reply	system_prompt 保持原样（{display_name} 不被替换）
U13	profile_memory 有 display_name=“小诺” → 两次调用	第一次替换，第二次一致（幂等）
U14	profile_memory 有其他可覆盖字段 → assemble_reply	对应字段也被替换
召回注入
#	用例	预期
U15	assemble_reply 时有相关事件 → system_prompt	包含 “## 相关记忆” 段落
U16	assemble_reply 时无相关事件 → system_prompt	不包含 “## 相关记忆”
U17	召回注入后 → 事件的 recall_count	+1
U18	emotional_context 有值 → 召回注入	情感匹配的事件优先
前端测试（需手动或 UI 自动化）
#	用例	预期
U19	打开记忆面板 → 看到事件列表	卡片列表，每张显示类型/内容/时间
U20	筛选 fact → 列表只显示 fact	类型筛选生效
U21	删除一个事件 → 列表更新	该事件从列表消失
U22	手动添加事件 → 列表更新	新事件出现在列表顶部
U23	编辑事件 importance → 列表更新	字段更新
U24	空库 → 记忆面板	显示空状态提示
U25	事件数量 > 100 → 列表	分页或滚动加载
trace 验证
#	操作	预期
T16	curl GET /api/memory/events → 响应	200, JSON 格式正确
T17	curl POST → 查 DB → 有新事件	event_id 存在
T18	curl DELETE → 查 DB → status=“dormant”	软删除
T19	有记忆时发消息 → 查 LLM 请求	system_prompt 包含相关记忆段
T20	改 profile_memory 的 display_name → 发消息 → 检查 LLM 请求	system_prompt 中 display_name 被替换
六、6.6 接线 + 端到端验收
提取触发接线
#	用例	预期
W1	聊 10 轮有实际内容 → 第 10 轮结束	触发提取，DB 有事件
W2	聊 10 轮纯闲聊 → 第 10 轮结束	触发提取，DB 无新事件（提取返回空）
W3	聊 9 轮 → 不触发	第 9 轮结束不提取
W4	聊 20 轮 → 第 10 轮和第 20 轮各提取一次	DB 有两批事件
W5	聊 7 轮后停 5 分钟 → IdleThink 补提取	DB 有 turn 1-7 的事件
W6	聊 10 轮 + 聊 7 轮后停 5 分钟 → 补提取 turn 11-17	DB 有补提取事件
召回注入接线
#	用例	预期
W7	Session A 提取事件 → 新建 Session B → B 第一个问题命中 A 的事件	system_prompt 包含 A 的事件
W8	Session B 问无关问题 → 召回不命中	system_prompt 不包含相关记忆段
W9	多个事件被召回 → 按时序排列	旧事件在前，新事件在后
W10	召回事件有 related_events → 关联事件也注入	system_prompt 包含关联事件
去重端到端
#	用例	预期
W11	第 10 轮提取"用户是 C++ 工程师" → 第 20 轮再提字面近似信息	不重复存储；同义改写信息应双份存储
W12	第 10 轮提取 importance=2 → 第 20 轮类似事件 importance=4 → 旧事件被 superseded	旧 status=“superseded”
W13	第 10 轮和第 20 轮事件同义相关但未达字面近似	双份存储（related/merge 语义阈值未实现，真 embedding 后重开）
衰减端到端
#	用例	预期
W14	新事件 importance=5 → 召回	在结果中，分数高
W15	30 天前事件 importance=5 → 召回	在结果中，分数降低
W16	90 天前事件 importance=1, recall_count=0 → 召回	可能不在结果中（分数低）
W17	90 天前事件 importance=1, recall_count=0 → IdleThink GC → 查 DB	status=“dormant”
W18	旧事件但 recall_count=10 → 不被 GC	status 保持 “active”
情感维度端到端
#	用例	预期
W19	用户当前情感 valence=0.8 → 召回 → 情感匹配的事件排名更高	情感 boost 生效
W20	用户当前情感 valence=-0.8 → 召回 → 消极事件排名更高	负面情感匹配
W21	情感模块不可用 → 召回	不带情感 boost，正常召回
回归测试
#	用例	预期
W22	全量 pytest tests/	880+ passed, 3 skipped
W23	Ruff 全仓	通过
W24	现有 memory_chunks 测试	全部通过（不破坏旧记忆）
W25	现有记忆召回测试	全部通过
W26	现有 IdleThink 测试	全部通过
W27	现有 session.py 测试	全部通过（assemble_reply 不退步）
W28	core 不 import shell	分层检查通过
W29	settings v2 读写正常	6.7 不退步
故障注入（trace）
#	操作	预期
T21	提取时 LLM 超时 → 对话流程	不崩，用户无感知，日志记录失败
T22	embedding 函数报错 → 提取	事件存储成功但 embedding=None，不崩
T23	sqlite-vec 查询报错 → 召回	BM25 + hash-bow 仍返回结果（多路降级）
T24	召回时 DB 连接断开 → 召回	返回空列表，不崩，对话正常继续
T25	IdleThink GC 时 DB 锁 → GC	跳过本轮 GC，下次重试
T26	system_prompt_locked 中没有 {display_name} 占位符 → 有 profile_memory	不崩，replace 无匹配不报错
T27	前端记忆面板打开时后端事件被 GC → 列表	已显示的不消失（前端缓存），刷新后消失
执行顺序
阶段	范围	类型
1	S1-S16, D1-D10, B1-B6	6.1 单元+边界
2	E1-E39	6.2 单元+容错
3	R1-R42	6.3 三阶段召回
4	I1-I16	6.4 IdleThink 集成
5	U1-U25	6.5 API + 前端
6	W1-W29, T21-T27	6.6 端到端 + 回归 + trace
7	T1-T20	各子任务 trace 验证（随阶段 1-5 执行）
覆盖统计
子任务	自动化	手动	小计
6.1 存储层	26	3	29
6.2 提取器	39	4	43
6.3 召回	42	4	46
6.4 IdleThink	16	4	20
6.5 UI+注入	18	7	25
6.6 端到端	12	7	19
trace	-	27	27
总计	153	56	209
816 + ~153 新增自动化 = ~970。实际可能因 mock 复用和 fixture 共享少一些，目标 880+ passed。

关键验收标准（6 条硬性）
W1：聊 10 轮 → 自动提取事件入库
W7：跨会话召回命中
W11：重复信息不重复存储
W17：90 天无召回事件被 GC
U11：system_prompt_locked 不覆盖记忆
W22：全量 880+ passed, 3 skipped
