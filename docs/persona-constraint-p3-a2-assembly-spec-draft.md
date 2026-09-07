# P3-A2 L1 组装 + 资产补全实现规格（v0.2）

状态：§9 盘点、D-A1～A6、traits 冲突口径、`tone_keywords` 单域口径与五预设入库对齐表均已落位；可进入实现。

输入：A1 基座（快照四列 + source 枚举预埋 p3_a2_l1_assembled）+ P1/P2 冻结资产 + 883f84b 冻结映射 + 四锚终版（v1.5 §8 :156）
v0.1→v0.2 演进：TA 完成 §9 五项盘点回填 + D-A1～A6 裁决；五预设入库从“逐字节复制”改为“对齐表回填”（盘点实锤：compositions 无完整 payload 字段）；traits 保全升级为双写对齐。

## 0. 范围
做：L1 组装器（纯函数）+ 资产四件（完整根+哈希解析 / 五标定预设入库 / traits 迁移三件套 / 写旁路清零）+ to_level 派生 + 确定性文案 15 条 + source 切换。

不做（防膨胀）：L3 谓词与 lint 常驻化（A3）、L4 retry/fallback（A4）、UX 端到端回归与 fixture 重跑门槛（A5）、输出侧检测（W3）、OCEAN 编辑 UI（P4 后定）、保护区文案人格化（D-A4 裁决：仅五预设三类，保护区不碰）。文案审计本批用 P1/P2 既有一次性 lint 脚本，常驻化留 A3。

## 1. 资产①：完整根 + 哈希解析
盘点落位：尚无专用 resolver，现 configs_dir() 仅凭 seeded default.yaml 选整根，旧配置遮挡风险确认（runtime_paths.py:62）；统一入口 corpus.yaml:12 目前只有路径无哈希字段；目标规则已在接线批骨架 :63。

实现：

manifest 载体 = corpus.yaml 内增 manifest 段（不建独立 manifest 文件——P2 终裁“YAML 单入口”，独立文件违反单入口）。manifest 内记录五份被引用源文件的逐项 SHA-256；manifest 不能记录自身哈希，避免自引用闭环；
manifest 的期望 SHA-256 由 B 层发布常量钉死，resolver 先校验 manifest，再校验其中五份源文件。只把实际 manifest 哈希写进快照不构成信任锚，不能替代发布常量；
当前盘点哈希如下；corpus 为加入 manifest 段前的基线哈希，实现后必须重算最终哈希并更新发布常量：

| 资产 | SHA-256 | 用途 |
| --- | --- | --- |
| `configs/persona_constraint_corpus.yaml` | `2b40dad720386642f2c386019f6c5ad75ef9e4c322b6b0b4ccfaa56e989d5564` | A2 修改前基线，不作为最终发布哈希 |
| `configs/persona_constraint_mappings.yaml` | `05e2a9001e3dde0dbfbafa6f523f00250b565d49bef56c8163debd45b60445c7` | manifest 逐项哈希 |
| `configs/persona_constraint_example_coverage.yaml` | `2be4a629bac8136d4da539322cf15a27d6885b583ab54350ee466ede498c813d` | manifest 逐项哈希 |
| `configs/persona_constraint_dimension_corpus.yaml` | `de12acd43c0deb8bbd297e477fe109739e901a59896a0e016388b74c5259fac5` | manifest 逐项哈希 |
| `configs/persona_constraint_structural_corpus.yaml` | `8f34b22d4d29070bcdfe3f61e9712a5cfe7086be4231663f4e2957de0db7256e` | manifest 逐项哈希 |
| `configs/persona_constraint_persona_compositions.yaml` | `889930cee23b6238738d4cef72b47504fe406e0acafb8bc9213141fdb7ce3334` | manifest 逐项哈希 |

加载器逐条校验，任一不符即 raise（fail-fast），禁止静默跳过或降级加载；
快照可追溯（D-A1 附加裁决）：persona_snapshot_json 内增 manifest_hash 字段（快照四列不动，不加列），记录组装时 manifest 实际哈希——每个会话可追溯到当时的资产版本；
resolver 新建（非改造 configs_dir）：白名单解析器，未知字段显式忽略、结构不符 raise，对旧 configs 残留字段遮挡免疫（T18 负控）；
运行时旧链路处置：configs_dir() 的 seeded default.yaml 选择逻辑保留给非 persona 配置，persona 链路切新 resolver——两链边界以资产类型划线。
## 2. 资产②：五标定预设入库（D-A5 落地区）
盘点实锤：冻结资产（configs/persona_constraint_persona_compositions.yaml:9）只定义名称、类型、档位签名及语料引用，无稳定 ID、数值 OCEAN、avatar/desc/base prompt，不能直接冒充完整可入库 payload。

### 2.1 冻结资产 × DB seed 对齐表

现有三条 seed（`xiao_nuo/a_ce/zhi_xin`）均不命中五个冻结签名，继续原样保留为 `unvalidated_custom`；五预设新增独立内置行，不覆盖、不借名对齐现有 seed。

| 名称 | 稳定 ID | 类型 | 冻结档位 `[O,C,E,A,N]` | 入库数值 `[O,C,E,A,N]` |
| --- | --- | --- | --- | --- |
| 温柔 | `builtin_wenrou` | style | `[mid,mid,low,high,high]` | `[50,50,17,83,83]` |
| 暴躁 | `builtin_baizao` | style | `[mid,mid,mid,low,high]` | `[50,50,50,17,83]` |
| 可靠 | `builtin_kekao` | behavior | `[mid,high,mid,mid,mid]` | `[50,83,50,50,50]` |
| 甜美 | `builtin_tianmei` | style | `[high,mid,high,high,low]` | `[83,50,83,83,17]` |
| 可爱 | `builtin_keai` | style | `[high,mid,high,mid,low]` | `[83,50,83,50,17]` |

数值映射固定为 `low=17/mid=50/high=83`：三个值均位于对应闭区间内部且以 50 对称。该映射只是把冻结档位序列化为 DB 整数的 v0.2 新定义，不是 P1 标定结果，也不声明档内数值差异具有额外行为效应。

| 字段 | 来源 | 状态 |
| --- | --- | --- |
| 名称、类型、档位签名、语料引用 | compositions 冻结资产 | 已冻结，逐字节消费 |
| 稳定 ID | v0.2 上表 | A2 新定义 |
| OCEAN 数值 | v0.2 `17/50/83` 映射 | A2 新定义，不声称 P1 锚定 |
| `avatar` | 名称首个 Unicode 字符 | A2 确定性投影，不进入语义锚 |
| `desc` | `内置已验证人格预设 · {name}` | A2 展示元数据，不进入 L1 |
| base prompt | A2 共用身份/隐私基础模板 | A2 新定义；五人格差异只由冻结 L1 资产与 15 条文案产生 |

物理复制原则不变：compositions 引用的语料资产进产品面时逐字节复制（任何字节差异破坏 P1/P2 锚定可追溯性）；
冻结资产的"档位签名不得另造"（D-A5 裁决）——签名是标定产物，入库只消费不修改；
入库写路径走 §4 统一通道（seed 路径为允许项）。
## 3. 资产③：traits 迁移三件套（v1.5 §8）
盘点落位：手写值双写现状——traits_json 与 raw_json.traits 同时存在（persona_repo.py:154、:393）；tone_keywords 为 reformatter 独立行为字段（rule_reformatter.py:84）；旧热编辑入口 togglePersonaEdit/savePersonaEdit（shell.js:1350、:1437）；创建器另有前端派生链（shell.js:1804、:1917）。

手写标签保全升级为双写对齐（D-A2 裁决采纳：原键保留 + derived_* 隔离，不迁独立表；明确取代 v1.3 覆盖原键的旧迁移口径）：
v15 迁移时两处手写值逐字节保全 + 一致性核对（T20）；
冲突裁决钉死：两处均为合法数组但不一致时，以 `raw_json.traits` 为准，保持原顺序与文本，并记录 `persona/traits_source_conflict` 审计；`raw_json.traits` 缺失或非法时回退合法的 `traits_json` 并记录原因；两处均缺失或非法时保全为空列表，不猜值；
移除编辑入口：togglePersonaEdit/savePersonaEdit 移除，验收 = 静态 grep 0 命中 + UI 冒烟无入口；
创建器前端派生链按 D-A6 方案 a 收口：删除 JS 中的 traits/desc/anchor 规则，预览调用无副作用的本地后端轻 API；API 与最终保存共用同一派生函数，前端只展示返回结果，失败时不得回退 JS 第二实现；
`tone_keywords` 单域口径确认：仅保留 local reformatter 输出侧消费，A2 不建输入侧同名域；未来扩域必须使用新字段并单独立规，不复用该键偷渡输入语义；
迁移实现：v15 schema（A1 是 v14），历史值不洗，只加不改。

## 4. 资产④：写旁路清零（D-A3 落地）
盘点落位写点全清单：

| 写点 | 位置 | 处置 |
| --- | --- | --- |
| CRUD | `persona_repo.py:115/:135/:189/:260` | 收敛进统一通道 |
| seed | `persona_repo.py:287` | 允许项（D-A3 裁决），走通道内 seed 路径 |
| 切换事务 active SQL | `session_binding.py:433` | 收编：改调 persona_repo 的 active setter，不直连 SQL（“不得成为永久旁路”裁决的兑现） |
| v15 迁移 | `engine.py` | 允许项（迁移写历史数据属合法旁路，显式列入） |
| 前端直写 | `togglePersonaEdit/savePersonaEdit` | 随 §3.2 移除 |
通道形态裁决：不新建 Gateway 文件；`persona_repo.py` 收敛为唯一写门面（CRUD/seed/active setter 全在 repo 层），`session_binding` 切换事务改调不自行提交的 transaction-aware active setter，保证 A1 原子事务边界不被 repo 内部 `with conn` 截断；
边界钉死：persona 配置写入 ≠ 用户画像记忆写入（semantic_extractor 的 agent_profile 链路独立，不属本批）；
哨兵：A2 完成一次性全量写点断言（盘点清单逐项核对 + repo 外 personas 写 SQL = 0），CI 常驻化进 A3（D-A3 裁决）。
## 5. to_level 派生
派生链（四锚终版）：ocean_json [O,C,E,A,N] 0..100（事实源不动）→ DIMENSION_ORDER 常量 → to_level（切点 ≤33 / 34-66 / ≥67，预注册，P4 判别数据重校）→ traits_json 派生缓存；
验收：边界值 33/34/66/67 × 五维 25 断言 + 派生幂等；
切点按预注册口径实现，不因实现期直觉微调（P4 重校是唯一合法变更入口）；
后端权威：to_level 派生唯一实现在后端——前端派生链处置随 D-A6（防双实现漂移）。
## 6. L1 组装器
```python
assemble_l1_prompt(persona_id, corpus_assets, frozen_mapping) -> AssembledPrompt
    # 纯函数：无时间戳、无随机、无 IO
    # 冻结映射机械查表（883f84b），映射本身进断言（T12）
```

口径组合（钉死）：

| 层 | 内容 | 确定性口径 |
| --- | --- | --- |
| L1 核心 | 模板 + 语料条目 + traits 派生 + 人格文案 | 同一人格两次组装逐字节一致（纯函数） |
| display_name 烧入 | `build_snapshot` 时查 `latest_profile_memory()` 烧入实际值 | 非纯函数（含记忆状态），不进 L1 验收 |
| 快照整体 | L1 产物 + display_name + manifest_hash = 实际生效 prompt 及其资产版本 | 逐字节回放审计（A1 T1 语义保持） |
display_name 不进 L1 核心：保纯函数 + 现有 conn-aware 机制不动；快照必须烧入：A1 快照立约理由 = 行为审计逐字节回放。两层各保各的口径，禁止混同；
组装顺序固定（模板段 → 语料段 → traits 段 → 文案段），顺序变更 = 规格变更；
组装失败：资产缺失 / 哈希不符 / 解析失败 → raise → A1 切换事务回滚 → 前端明确失败。禁止降级旧模板静默组装。
## 7. source 切换
新会话快照 source = p3_a2_l1_assembled（A1.1 R5 预埋值，只加值不改语义）；
存量会话快照逐字节不变（历史不洗）；
bootstrap 链路同步：启动创建的首个会话同样走 L1 组装 + 新 source。
## 8. 确定性文案 15 条（3 类 × 5 人格，D-A4 落地）
三类：switch 确认语 / 确定性回答确认语 / 降级语，五预设各一套；
边界（D-A4 裁决）：仅覆盖五预设的三类确定性文案。下列保护区逐字节保持既有确定性输出，不得读取人格文案表：安全/危机固定回复；Consent 披露、询问、拒绝、超时与撤销；算术/质量警示及审计块；工具、任务、计划和下载结果；隐私、离线与出站策略提示；API/schema 错误码；迁移、恢复、冲突与数据完整性错误；
流程：TA 起草 → 过 P1/P2 一次性 lint 五项（禁用词 / L4 / 短前缀复制 / 无证据绝对承诺 / 内部机制泄漏）→ 0 红后冻结进 YAML + manifest 登记哈希；
验收：15 条全过 lint + 确定性路径不进 backend 回归保持 + 五预设对应查表断言。
## 9. 盘点事实清单（TA 已回填，v0.2 落位）
corpus.yaml:12 统一入口，仅路径无哈希字段；五份被引用资产 SHA-256 已算定，corpus 自身记录修改前基线哈希，最终发布哈希须在 manifest 段落地后重算；
无专用 resolver；configs_dir() 仅凭 seeded default.yaml 选整根（runtime_paths.py:62）；目标规则接线批骨架 :63；
compositions 仅名称/类型/档位签名/语料引用，无完整 payload 字段（§2 对齐表）；
traits 手写值双写（persona_repo.py:154/:393）；tone_keywords = reformitter 行为字段（rule_reformatter.py:84）；编辑入口 shell.js:1350/:1437；创建器派生链 shell.js:1804/:1917；
写点：persona_repo.py:115/:135/:189/:260/:287 + session_binding.py:433（§4 表）。
## 10. 测试清单（T12-T26）
| # | 断言 |
| --- | --- |
| T12 | 冻结映射逐条机械查表：883f84b × 五预设全量，映射本身进断言 |
| T13 | L1 纯函数：同一预设两次组装逐字节一致（五预设） |
| T14 | 组装输出与冻结映射逐字节一致 |
| T15 | `to_level` 边界：33/34/66/67 × 五维 25 断言；五预设每维数值均属于 `{17,50,83}`，且 `to_level(数值)` 与冻结档位签名逐维一致 |
| T16 | 派生幂等：同输入两次派生逐字节一致 |
| T17 | 快照完整性：新会话快照 = L1 产物 + display_name + manifest_hash = 实际生效 prompt 逐字节 |
| T18 | 旧 configs 遮挡免疫：残留字段注入 → 解析行为不变；结构不符 → raise |
| T19 | manifest 发布哈希或五份源文件逐项哈希任一不符 → 加载 raise、组装拒绝（负控） |
| T20 | 双写对齐：`traits_json` 与 `raw_json.traits` 手写值迁移前后逐字节一致 + 冲突/回退判例 |
| T21 | 编辑入口及 JS 派生规则移除；UI 冒烟无热编辑入口；预览 API 与最终保存共用派生结果 |
| T22 | source 切换：新会话 `p3_a2_l1_assembled`；存量快照逐字节不变 |
| T23 | 组装失败回滚：注入资产缺失 → 切换事务全回滚 → API 明确报错（T4 同型） |
| T24 | 文案 15 条：五项 lint 0 红 + 五预设对应查表断言 + 保护区未被越界改动 |
| T25 | 确定性路径回归：身份查询等确定性路径不进 backend（既有行为保持） |
| T26 | 写旁路清零：repo 外 personas 写 SQL = 0 + session_binding 走 repo setter + seed/迁移显式豁免 |
## 11. 验收行（写进方案后不可移动）
T12-T26 全绿；
五预设 × 全量派生一致性（T13+T14）；
文案 15 条 lint 0 红 + 保护区零越界（T24）；
解析免疫负控通过（T18+T19）；
source 切换判例通过且存量快照零漂移（T22）；
写旁路清零：§4 处置表逐行核对通过（T26）；
全量回归 ≥ 1306 passed 基线；
文档同步放本批最后一步。
## 12. 决策点
已裁落位（D-A1～A6）：

| # | 裁决 |
| --- | --- |
| D-A1 | 逐项哈希；manifest 记五份源文件各自 SHA-256；发布常量钉 manifest 期望哈希；运行快照另记实际哈希 |
| D-A2 | 原 traits 保全 + `derived_*` 隔离；取代 v1.3 覆盖原键旧口径 |
| D-A3 | A2 一次性全量写点断言，A3 转 CI 常驻；seed/迁移显式列入允许项；session_binding 不得永久旁路 |
| D-A4 | TA 起草 → lint → 冻结；仅五预设三类，保护区不人格化 |
| D-A5 | 档位签名只取冻结资产；稳定 ID、展示元数据与 `17/50/83` 数值映射按 §2.1 作为 v0.2 新定义，不声称 P1 锚定 |
| D-A6 | 采纳方案 a：后端权威 + 前端预览调用轻量本地 API；API 与保存共用派生函数，无 JS fallback |
| 确认 1 | 双写冲突以合法的 `raw_json.traits` 为准；缺失/非法时回退 `traits_json`；冲突与回退均审计 |
| 确认 2 | `tone_keywords` 确认为 local reformatter 输出侧单域，A2 不建输入侧域 |

## 13. 执行顺序
资产①②（manifest 段 + resolver + 入库）→ 资产③（v15 迁移三件套 + 入口移除）→ to_level 派生 → L1 组装器 → 文案 15 条 → 资产④（写旁路清零）→ source 切换 → 测试收口 → 文档同步（最后）。

估量 1-2 晚不变；对齐表回填质量是唯一的实现批风险前置项。
