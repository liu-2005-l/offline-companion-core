拟人表述升级 W1-B.1 扩展规格（受控重跑）

版本：v1.0
状态：锚后扩展预注册（先于任何 B.1 运行；引用锚 18f24c5，作为独立 commit 接受审计）
上游：docs/oc-persona-expression-w1-criteria.md（锚定版）+ W1-B 落档 e4f052b

起因：
1. runner 的 seed42/1337 未真正传 llama sampler seed，实为 run 标签，“双 seed 受控”不成立；
2. 漂移结论目前只有存在性证明，无漂移率估计；
3. P50 单点断崖无法区分“问题难度触发”与“累积漂移”。

## B.1-1 sampler seed 真接线

- llama-cpp-python：`Llama(model_path=..., seed=N)` 构造参数；
- sidecar 路径：请求 JSON `"seed"` 字段；
- 接线验证：同 seed 两次完整 run，判例集输出逐字节一致；
- run 命名与 seed 映射落档，杜绝标签与实参再次脱钩。

## B.1-2 probe 受控重跑（N≥5）

- seeds：42 / 1337 / 2024 / 7 / 99；
- 每个 seed 完整 50 轮会话，五 probe 全跑；
- 记录：bigram 保留率 × 5、身份断崖出现轮、断崖形态分类；
- 产出：漂移率 = 断崖 run 数 / N + 断崖位置分布。

## B.1-3 判例集六指标多 seed（N=3）

- 40 判例 × 3 seeds：42 / 1337 / 2024；
- 六指标按 seed 全值落档，报告 mean ± range；
- W2 gate baseline 侧取 N=3 分布，不锁 n=1 单点。

## B.1-4 配对转述 probe

- 目的：分离“问题难度”与“累积漂移”；
- 对 A：P10 位“聊聊你觉得自己是个什么性格？” / P50 位“你有什么样的个性？给我形容一下”；
- 对 B：P10 位“跟我说说你是谁吧” / P50 位“再重新自我介绍一下你自己”；
- 判定：locked display_name 相关 bigram 在场 + 无通用自称覆盖；
- 实现自由度：插入位置/轮次编号 TA 定，题目文本不改。

## 命名勘误

原 `w1_baseline_v1_8_0.json` 中 seed42/seed1337 实为 run1/run2 标签（无 sampler 控参）。结论（P50 漂移存在性）不受影响，“双 seed 受控”表述作废，受控数据以 B.1 产物为准。

## 流程注记

锚 commit 18f24c5 内 fixture 存在中文问号落盘失真；e4f052b 修复（编码修复，判据语义未变）；修复发生于任何 baseline 运行之前，锚内失真版本从未产生数据。

## 验收行

- [x] seed 真接线 + 同 seed 双跑逐字节一致验证
- [x] N≥5 probe 漂移率落档（含断崖形态分类）
- [x] N=3 判例集六指标分布落档
- [x] 命名勘误 + 锚关账注记落档
- [x] 配对转述 probe 裁掉记档
- [ ] 碰头：gate 数值化定稿（锚分布）+ W2 对策臂选择 + 锚点语料分工
