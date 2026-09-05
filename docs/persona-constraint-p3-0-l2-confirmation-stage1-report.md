# P3-0 L2 确认集第一段执行报告

版本：v1.1（外部盲审解盲与失败分支闭合）  
状态：**最终 `9/32` 未过 `22/32`；停止剩余 128 对并进入 `no_effect`**  
规格：`fixtures/persona_constraints/p3_0_l2_confirmation_stage1_spec.yaml`

## 0. 预注册裁决

- 角色：确认集第一段兼外部非产出者判别 gate；
- 规模：四个入选目标格各 8 对，共 32 对、64 个新输出；
- 放置：每格 candidate 左右各 4，总体 16:16；
- 判定：`indistinguishable` 计 failure，至少 `22/32` 才允许续跑剩余 128 对；
- 精确单侧二项：`P(X>=22|n=32,p=0.5)=0.025051229866221547`；`21/32` 为
  `0.055092082591727376`，不通过；
- 失败分支：少于 22 个 success 时停止确认集，进入 `no_effect` 评估。

## 1. 独立性与矩阵

- 24 条新 prompt：C/A/N 各 8 条；A-low 与 A-high 共用 prompt 文本，但各自产生目标档位输出；
- 8 个 fresh seeds：每条 prompt 只绑定一个 seed，与 screening 及历史 seeds 无交集；
- prompt 与 screening prompt、P2 注入示例问句均无包含关系，最大近似度门线 `<=0.75`；
- 生成矩阵：`4 targets × 8 prompts × (baseline + candidate) = 64 outputs`；
- 不复用 screening prompt、seed 或输出；自动 gate 红样本不重生成、不剔除。

## 2. 生成结果

- 64 个输出全部生成并落盘，32 个盲审 pair 完整；
- 自动 gate 全绿 `54/64`；禁用与 L4 无公开异常；
- A-high：`15/16` 全绿，finish/完整终止红 1；
- A-low：`12/16` 全绿，finish/完整终止红 4；
- C-low：`12/16` 全绿，finish/完整终止红 4；
- N-low：`15/16` 全绿，finish/完整终止红 1；
- 上述为 candidate 与 baseline 合并诊断；外部审读完成件封存后才打开 key 拆分 candidate 硬 gate。

## 3. 外部盲审与解盲

- 32 项选择完整，分布为 `left=6 / right=12 / indistinguishable=14`；
- `14/32=43.75%` 不可判按预注册协议计 failure；
- 原始 candidate 胜数 `10/32`；candidate 自动硬 gate 绿 `28/32`；
- 一条原始胜出 candidate 的 finish/完整终止 gate 红，联合 success 降为 `9/32`；
- 分格最终 success：A-high `2/8`、A-low `0/8`、C-low `4/8`、N-low `3/8`；
- candidate 左置时原始胜 `4/16`、最终 `3/16`；右置时原始胜及最终均为 `6/16`；
- 评审 left 选择与 candidate 同侧 `4/6`，right 选择与 candidate 同侧 `6/12`。这只是位置诊断，不是评审答对率。

由于 `9 < 22`，按生成前冻结的失败分支停止剩余 128 对。四格只完成各 8 对，不标为单格
`confirmed_no_effect`；整体进入 `no_effect_observed_within_preregistered_grid` 收口。

## 4. 证据哈希

| 资产 | SHA-256 |
| --- | --- |
| stage-1 spec | `84F87007D25D78F00BB81B688CD99A165D166FBDC35FA1C60C2CD97E08514FF2` |
| 64 outputs raw | `EF3DD4BB408CC9647C6AC2459D47B8C92D66BB7EBF8291B3E19A3F4DFBA8165C` |
| 32-pair blind packet | `2FBCEB85D8780B5EA735F5295D83E55BD1F9EC4E7D5C34C08C496E7121F79DBE` |
| sealed blind key | `B45F310A97B3466BD9AB16C555622FB178B405B3924A1AACEB697027BF7862C1` |
| completed external review | `AC891DF3699016EAD0C4CBE4DBEC05FDA4AF1A880F29C73B0CC70BA4F0BE39A1` |
| blind review verdict | `A76D62E43F982EC2CFE4670F9557A147BC87854BE0A52D6680015231155C6F1E` |

完成件哈希先写入独立 `.sha256` 封条，再读取 sealed key。解盲裁决另存于
`artifacts/persona_constraints/p3_0_l2_confirmation_stage1/blind_review_verdict.json`。

## 5. 验收状态

- [x] 32/22 判定线与双分支在生成前冻结；
- [x] fresh prompt/seed 与 screening 零复用；
- [x] 64 个原始输出完整且无失败重抽；
- [x] 32 对审包零参数身份字段；
- [x] 每格 8 对的 `4:4` 放置由生成器结构断言保证；
- [x] 外部评审完成 32 项选择；
- [x] 完成件封存后打开 key，叠加 candidate 硬 gate 复算 success；
- [x] 最终 `9/32` 未过线，停止续跑并执行 `no_effect` 分支。
