# W2 并行污染数据

本目录中的 JSON 是 2026-08-30 首轮 B/C 矩阵发生并行模型推理时留下的污染证据。

- 仅供审计并行污染的时间线与输出差异；
- 不进入任何指标统计、gate 判定、盲评或发布裁决；
- W2 终局数据只认上级目录的 `w2_arm_a_matrix.json`、`w2_arm_b_matrix.json`、`w2_arm_c_matrix.json` 及 `w2_final_matrix.json`；
- B/C 已分别单进程重跑，串行产物的哈希固定在 `w2_final_matrix.json`。

废弃原因：B 后台续跑与 C 同时占用本地模型推理资源，违反预注册的 A → B → C 串行实验约束，不能用于单变量归因。
