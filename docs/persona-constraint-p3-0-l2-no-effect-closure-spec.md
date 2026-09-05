# P3-0 L2 `no_effect` 收口规格

版本：v1.0（执行预注册失败分支）  
状态：**L2 解码参数人格调制不采用；P3-A 按无采样 DTO 形态开工**  
机器规格：`fixtures/persona_constraints/p3_0_l2_no_effect_closure_spec.yaml`  
机器规格 SHA-256：`5F9F9F74FA4D9B239F76321AE1233968904229C06F8F7126396CAC64494F3627`

## 0. 裁决

确认集第一段预注册门线为 `22/32`，`indistinguishable` 计 failure，candidate 自动硬 gate 红同样计
failure。外部盲判完成件在开 key 前校验并封存，解盲后原始 candidate 胜数为 `10/32`；其中一条胜出
candidate 的完整性 gate 红，最终 success 为 `9/32`。本轮未过门线，剩余 128 个确认 pair 停止生成。

因此执行已冻结的失败分支：L2 解码参数人格调制记为
`no_effect_observed_within_preregistered_grid`。这不是实验异常，也不外推为所有模型、所有采样参数均无效；
它只说明当前 1.5B 模型、冻结语料、预注册 temperature/top_p 网格内的效应不足以通过人工可感知与硬 gate 联合门线。

## 1. 解盲对账

| 目标格 | candidate | 盲判分布（左/右/不可判） | 原始胜数 | candidate gate 绿 | 最终 success |
| --- | --- | --- | ---: | ---: | ---: |
| A-high | `temperature_p010` | `0/2/6` | 2/8 | 8/8 | 2/8 |
| A-low | `top_p_m010` | `2/2/4` | 0/8 | 6/8 | 0/8 |
| C-low | `temperature_p005` | `2/5/1` | 5/8 | 6/8 | 4/8 |
| N-low | `temperature_p010` | `2/3/3` | 3/8 | 8/8 | 3/8 |
| **合计** | — | `6/12/14` | **10/32** | **28/32** | **9/32** |

candidate 左置与右置严格各 16 条。左置时原始胜 `4/16`、硬 gate 后 `3/16`；右置时原始胜及最终
success 均为 `6/16`。评审选 left 的 6 条中有 4 条与 candidate 位置一致，选 right 的 12 条中有 6 条
一致；这些是位置诊断，不是“评审答对率”，因为 pair 不存在独立真值标签。14/32（43.75%）不可判本身按协议
进入失败侧。

用户点名的第 23 对对应 `blind_id=4f1d0c694cdfa775`：语义盲判选择了左侧 candidate，但 candidate 的
finish/完整终止 gate 红，因此该条从原始胜数扣除。自动 gate 没有被人工方向判断覆盖。

## 2. 证据链

1. 有效 screening 完成 320 个输出；30 个自动 gate 合格 arms 中 25 个未过 `3/4` 方向筛选线，仅 5 个过线，
   固定排序后留下四个目标格 candidate；
2. O-low/O-high/E-low/E-high 共 **4** 个 O/E 外档目标格全部无候选；连同 C-high/N-high，共六格为
   `screened_no_candidate_within_preregistered_grid`；
3. 第一段 32 个全新 pair 中有 14 个不可判，输出差异大量低于外部评审可感知阈值；
4. 解盲后硬 gate 联合 success 为 `9/32 < 22/32`，触发预注册停止分支。

首轮 prompt 泄漏批继续整批隔离，不进入上述统计。平衡重放与第一段均保持 candidate 左右严格平衡，排除了旧批
arm 内 `4:0/0:4` 放置耦合。

## 3. 十格状态

- `O_low/O_high/C_high/E_low/E_high/N_high`：`screened_no_candidate_within_preregistered_grid`；
- `C_low/A_low/A_high/N_low`：`confirmation_stage1_gate_failed`；
- 十格解码 delta 均写为带 provenance 的 `0.0/no_change`；
- 四个第一段目标格不得写成 `confirmed_no_effect`：每格只完成 8 对，未完成预注册的单格 `n=40` 确认；
- 五个 mid 档继续是设计性 baseline `no_change`，不冒充实验结论。

## 4. P3-A 工程后果

- 不新增人格专用采样 DTO，不为人格改 `GenerationOptions` schema，不应用 OCEAN 解码 delta；
- 保持现有采样默认值；人格调制收敛到 prompt/文本组装；
- P3-A 仍须接通 L1 人格组装、L3 降档触发与冻结语料选择、L4 已冻结 retry/fallback；
- 若未来重开 L2，必须先冻结新网格并使用独立 prompt/seed/output，禁止从本批失败 arms 事后挑第二名。

## 5. P4 观察项

筛选时 A-high 与 N-low 都选到 `temperature_p010`。它只说明两格共享同一解码候选，不能作为两人格可辨的证据；
作为 P4 共线观察保留，但本裁决后不进入运行时人格采样协议。

## 6. 验收行

- [x] 外部 32 项选择完整、枚举合法、ID 与公开 packet 顺序一致；
- [x] 完成件 SHA-256 在开 key 前独立封存；
- [x] 解盲结果由 completed review + sealed key 机械复算；
- [x] `9/32 < 22/32`，剩余 128 对明确停止；
- [x] 十格状态、零 delta 与工程后果写入机器规格；
- [x] 不把第一段失败升级为单格 `confirmed_no_effect`，不作网格外推断。
