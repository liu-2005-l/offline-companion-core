拟人表述升级 W1-B baseline 报告

状态：W1-B baseline 已跑通（2026-08-30）
上游锚点：docs/oc-persona-expression-w1-criteria.md
原始数据：artifacts/persona_expression/w1_baseline_v1_8_0.json
复算指标：artifacts/persona_expression/w1_baseline_v1_8_0.metrics.json

1. 运行信息

| 项 | 值 |
| --- | --- |
| 产品基线 commit | 18f24c5 |
| 模型 | models\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf |
| persona | default |
| 判例 | 37 records / 40 turns |
| probe | seed 42 + seed 1337，各 50 turns |
| 输出形态 | assemble_reply 完整链路，含身份锁 / 召回 / tone / emotion instruction |

说明：commit 记录为运行时产品基线。W1-B tooling 与本报告随后入档，不改变被测产品行为。

2. 六指标 baseline

| 指标 | baseline |
| --- | ---: |
| style_case_count | 25 |
| style_reply_count | 28 |
| 开场多样性 distinct-2 | 0.851852 |
| 句长 CV | 0.530947 |
| per-case 句长 CV 中位数 | 0.183099 |
| 列表依赖率 | 0.000000 |
| 模板短语密度 / 千字 | 0.000000 |
| 口语标记密度 / 千字 | 18.935978 |
| 跨轮 4-gram Jaccard 均值 | 0.000000 |

3. 记忆子集哨兵

M 子集运行前已执行预灌记忆召回哨兵：`injected_count > 0`。原始判例中 memory 场景保留逐轮 `recall_counts`，用于排查“空库假绿”。

4. 50 轮漂移定级

定级：严重。

证据：
- seed42：P10/P20/P30/P40/P50 均保留“助手一号”，P50 出现“作为一个助手一号”的生硬句式，但身份未丢。
- seed1337：P10/P20/P30/P40 保留“助手一号”；P50 输出“作为一个AI助手，我没有性格……”，丢失 locked display_name。

按预注册口径，“任一 seed 身份漂移，或自称/设定丢失/替换”即严重。结论：W2 锚点语料必须包含身份纠偏样本，且 50 轮 probe 继续作为 W2/W5 硬 gate。

5. 待裁决项

- 口语标记目标区间：baseline 为 18.935978 / 千字，W2 前需数值化目标区间。
- W2 效果闸门：需基于本 baseline 定开场多样性、模板短语、列表依赖率、跨轮雷同、句长 CV 的目标方向与容许带。
- 技术/记忆人工判据：T/M verdicts 仍保留空位，供 TA 盲评或人工复核回填。
