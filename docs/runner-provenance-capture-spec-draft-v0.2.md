# Runner Provenance 与 Candidate Capture 规格 v0.2

> **状态**：已冻结并闭合——B0/B0.5/B1/B2/B3 全部落位，全量基线 1597 passed、3 skipped。
>
> **批次定性**：runner 基建补强——零新检测机制、零检测逻辑变更，纯可归因性与审计增量。
>
> **修订说明**：v0.1→v0.2 修订由 TA 回填驱动，三处 v0.1 设计错误已修正（见 §10）。

## 1. 背景锚点

### 1.1 Checkpoint 无 provenance → 跨批差异不可归因

2026-10-04 盲评归因确认：W2 A/B 分日生成（A 08-30 / B 08-31 且 `resume=true`），A 臂 08-30→10-03 代码层漂移在归档层面无机械证据。

### 1.2 Candidate capture 未固化 → 分析不可复现

2026-10-04 P2-2 记档确认首扫分数不能预测 retry 成败：first/retry 双候选分析依赖现场调试手段，归档产物无固化 capture 则事后不可复现。

### 1.3 Commit hash 不足

echo retest 产物记录 HEAD=`8d6cb4b`，实际生成时工作区已包含后来提交为 `13ec263` 的改动。仅 commit hash 会把“修复后”误记为“修复前”状态。dirty 标志与 worktree 指纹是必须项，不是增强项。

## 2. 范围与非目标

### 2.1 范围

- `scripts/run_persona_expression_w2.py` 与 `scripts/run_w3_p2_repetition_retest.py` 两个 runner 接线。
- 共享 helper 模块：provenance 构造、resume 对账、worktree 指纹、capture 聚合。
- `session.py` 可选只读 capture sink。first/retry 正文仅存在于 core 局部变量（`session.py:641`、`:669`），`AssembleReplyResult` 只含最终 reply 与 trace（`session.py:325`），runner 侧物理取不到中间候选，必须在 core 判定完成后传出。
- `scripts/run_identity_reminder_echo_retest.py` 接 provenance，落顶层 `provenance`；不接 capture（无 checkpoint/resume/retry 链，D4）。
- P2-2 lock/checkpoint 路径补 `.gitignore`。
- 窄测覆盖全部 AC 判例。

### 2.2 非目标

- 旧 checkpoint 不回填。Resume 时仅记 `legacy_provenance_missing` 警告，不伪回填、不宣称无漂移。
- 不做 runner 框架抽象；helper 仅限上述四块纯逻辑。
- 零检测逻辑变更：guard/detector 文件与控制流零改动；`session.py` 仅新增 sink 参数与判定完成后的旁路 push，不改任何条件分支。
- 不伪造采样参数指纹。两 runner 未显式传 `temperature/top_p`，`create_chat_completion()` 只传 `messages/max_tokens/stop`（`backend.py:287`），指纹只记实际存在的配置。

## 3. 分工总纲

| 维度 | 载体 | 覆盖范围 |
|---|---|---|
| 代码面 | `git_commit + git_dirty + worktree_fingerprint` | 生成时逻辑状态，含未提交改动的内容差异 |
| 配置面 | `config_fingerprint` | runner 消费的模型、seed、采样、开关和输入文件 |
| 时间面 | `created_at + resumed_history` | 分批运行事实 |

core 内常量不进 `config_fingerprint`，由代码面指纹覆盖；配置面只记录 runner 声明并实际消费的内容。两轴互补，不重复。

## 4. 设计 A：Checkpoint Provenance

### 4.1 字段表

| 字段 | 类型 | 来源 | 语义 |
|---|---|---|---|
| `created_at` | ISO8601 | checkpoint 首次创建时刻 | 分批运行证明 |
| `git_commit` | 40-hex | `git rev-parse HEAD` | 生成时 HEAD |
| `git_dirty` | bool | `git status --porcelain` 非空 | 未提交改动标志 |
| `worktree_fingerprint` | hex | §4.2 | 同 commit 不同改动内容的区分指纹 |
| `config_fingerprint` | dict | §4.3 | runner 声明配置面快照 |
| `resumed_history` | list | resume 时追加 | 每条 `{resumed_at, git_commit, git_dirty, worktree_fingerprint}` |
| `code_drift_detected` | bool | 对账产物，sticky | 一旦为 true 保持 true |
| `config_drift_detected` | bool | 对账产物，sticky | config 指纹不一致 |

### 4.2 Worktree Fingerprint

`git_dirty` 只有布尔值，无法区分“同一 commit、两次都 dirty、但改动内容不同”。冻结算法：

1. tracked 改动：对 `git diff --binary HEAD` 的整体输出计算 SHA-256；
2. 未忽略 untracked：对 `git ls-files --others --exclude-standard` 排序后逐文件计算内容哈希，再与路径拼接计算整体 SHA-256；
3. 对上述两部分拼接结果再次计算 SHA-256，得到 `worktree_fingerprint`。

`--exclude-standard` 尊重 `.gitignore`，因此 runner 自产文件必须先进入 ignore，否则会污染指纹。

### 4.3 Config Fingerprint：声明式五类键集

Runner 声明自己消费的键，helper 只序列化、不硬编码。声明但读不到时直接失败，不静默写入 `None`。

| 键类 | W2 实际键集 | P2-2 实际键集 |
|---|---|---|
| model | 模型路径、size、mtime | 同左 |
| seeds | seed、case/probe seeds | seed |
| sampling | `max_tokens`、其余参数来自 llama.cpp 默认值、`llama_cpp` 版本 | 同左 |
| switches | style/identity 开关、cases/probe skip | guard 开关、运行阈值/比较符/ngram、L4 发布资产、global/local gate |
| input_files | cases/probe/persona 路径与 SHA-256 | cases/validation/persona 路径与 SHA-256 |

输入文件记录 SHA-256：`dirty=true` 只能说明工作区不干净，不能复现具体输入；文件哈希让数据自描述。

### 4.4 采集时序

Provenance 与 worktree 指纹必须在任何 runner 输出写入前采集：

1. `.gitignore` 补丁生效；
2. 采集 provenance；
3. 创建 lock、checkpoint 或其他输出。

P2-2 lock/checkpoint 当前未被 `.gitignore` 覆盖；若先创建再采集，会造成 runner 自污染，使 dirty 永远为 true，worktree 指纹也包含自产文件。

### 4.5 Resume 对账（D1）

对账 current `git_commit/worktree_fingerprint/config_fingerprint` 与 checkpoint provenance：

- commit 或 worktree 指纹不一致：`code_drift_detected=true`（sticky），stderr 显式警告并包含双方指纹；
- config 指纹不一致：`config_drift_detected=true`（sticky），stderr 警告并包含差异键名；
- warn + continue，不阻断；
- resume 时重写 checkpoint 并追加 `resumed_history`；
- legacy checkpoint 无 provenance 时仅警告 `legacy_provenance_missing`，不伪回填、不宣称无漂移，对账跳过。

### 4.6 失败语义

| 状况 | 处置 |
|---|---|
| `git rev-parse HEAD` 失败或空输出 | 拒绝启动，非零退出，并提示检查 Git 与仓库根目录 |
| 任一 Git 子命令异常 | 同上拒绝 |
| `git status --porcelain` 空输出 | 合法 clean，正常生成 |

禁止静默空值和 `unknown` 等占位值。伪 provenance 比无 provenance 更危险。

## 5. 设计 B：Candidate Capture

### 5.1 `session.py` 只读 Capture Sink

- `session` 增加可选 `capture_sink`，默认 `None`。
- 不传 sink 的生产调用行为与现状逐字节一致。
- Push 点为 first 判定完成后与 retry 判定完成后，均只在判定完成后旁路取值，不进入条件分支。
- Push 内容为候选正文与原始 decision DTO，不转译、不复算：`l4_decision` 与 `CrossTurnRepetitionDecision`。
- 单一 `pattern_family/verdict` 无法覆盖双门出口，双门 decision 是冻结 schema。
- Sink 是抽象可调用，core 不知道 runner 存在，不形成分层违规。

### 5.2 Capture 随 Checkpoint 保存并最终聚合

- Capture 逐条随 checkpoint 保存；
- 跑完后统一聚合到 `<matrix_stem>.candidates.json`；
- resume 时读取旧 captures 并合并，中断不丢数。

### 5.3 记录结构

```json
{
  "runner": "w2|p2_retest",
  "arm": "A|B",
  "source_kind": "case|probe|validation",
  "seed": 42,
  "scenario_id": "...",
  "turn_index": 0,
  "retry_taken": false,
  "first": {
    "text": "首扫命中原始文本",
    "l4_decision": {"...": "原始 DTO"},
    "repetition_decision": {"score": 0.09090909, "...": "原始 DTO"}
  },
  "retry": {
    "text": "retry 后文本",
    "l4_decision": {},
    "repetition_decision": {}
  }
}
```

- Uniform capture：无 retry 时 `retry_taken=false`，但 first 必须在场；成功路径同样可归因。
- Retry 后仍失败并走 fallback 时，retry 记录照常保存；终态文本已存在于矩阵，不在 candidates 重复保存。

### 5.4 Join 键

冻结六元 join 键：

`runner + arm + source_kind + seed + scenario_id + turn_index`

可附 `turn_id` 做冗余校验。

### 5.5 Sidecar Meta

```json
{
  "matrix_path": "...",
  "matrix_sha256": "...",
  "capture_complete": true,
  "legacy_gap": null
}
```

Legacy checkpoint resume 时必须写入 `capture_complete=false` 与 `legacy_gap`，不得静默产生“完整”假象。

## 6. `.gitignore` 补丁（B0.5）

P2-2 lock/checkpoint 路径加入 `.gitignore`。这是 B1 判例纯净性的前提，必须先于 helper 落地。

## 7. Checkpoint 结构与 Loader 剥离

Checkpoint payload 当前会原样嵌入最终矩阵：W2 每 `arm×kind×seed` 一文件，P2-2 每 `arm×seed` 一文件；两 runner resume 都是发现文件后直接 `json.loads()` 返回。

冻结结构：

```json
{
  "provenance": {},
  "captures": [],
  "payload": {}
}
```

`payload` 为现有业务数据原样。Loader 读取全量 checkpoint，但只把 `payload` 返回矩阵；provenance/captures 留在 checkpoint。Loader 之外禁止出现 checkpoint raw `json.loads()`，由 AC-11 grep 哨兵锁定。

## 8. 验收行

| # | 验收行 | 判例形态 |
|---|---|---|
| AC-1 | 新 checkpoint provenance 全字段在场：`created_at/git_commit/git_dirty/worktree_fingerprint/config_fingerprint/resumed_history` | 字段白名单正控 |
| AC-2 | Git 命令失败或空 HEAD 时拒绝；空 porcelain 为合法 clean | 负控与正控 |
| AC-3 | 同 commit 不同改动内容产生不同 worktree 指纹；dirty 工作区写入 `git_dirty=true` | 内容变更判例 |
| AC-4 | Resume 跨 commit/worktree/config 时对应 drift 标志 sticky、stderr 警告可见；同状态重入不误报 | mock 与负控 |
| AC-5 | Legacy checkpoint resume 产生 `legacy_provenance_missing`，不伪回填并跳过对账 | 旧格式 checkpoint 判例 |
| AC-6 | Capture sink 默认关闭；不传 sink 的生产调用行为与改造前逐字节一致 | `sink=None` golden |
| AC-7 | Retry 场景含 first+retry 双记录及双门 decision；无 retry 时 first 在场且 `retry_taken=false` | 正控与负控 |
| AC-8 | Capture 分数等于 `CrossTurnRepetitionDecision.score` 原始全精度值，不复算 | trace 对照 |
| AC-9 | 中断 resume 合并旧 captures 不丢；legacy 聚合标记不完整与缺口 | 半量 checkpoint 判例 |
| AC-10 | 六元 join 键唯一，A/B 同场景同 seed 与多轮 case 均不撞键 | 两类撞键负控 |
| AC-11 | Loader 剥离审计字段，矩阵 schema 零漂移；loader 外无 checkpoint raw `json.loads()` | 白名单与 grep 哨兵 |
| AC-12 | Provenance 采集不受 runner 自产 lock/output 污染 | `.gitignore` 时序判例 |
| AC-13 | Echo retest 产物顶层 `provenance` 在场 | 正控 |
| AC-14 | 既有矩阵 artifacts 结构零漂移，summarize 类脚本兼容 | 兼容判例 |
| AC-15 | 两 runner 均接线，helper 为单一事实源 | grep 哨兵 |

## 9. 批次拆解

- **B0**：本 v0.2 docs-only commit，提交后冻结。
- **B0.5**：`.gitignore` 补丁，先行小 commit。
- **B1**：helper 模块（provenance、worktree 指纹、对账、capture 聚合）与 AC-1~5、AC-9~12 窄测。
- **B2**：`session.py` capture sink、两 runner 接线与 AC-6~8 判例。
- **B3**：echo retest 顶层 `provenance`（AC-13）、文档同步与 W3 收口挂账项转闭合（已完成）。

预计 B1-B3 共 1–2 晚；sink 本身较小，B2 工作量主要来自判例密度。

## 10. v0.1 → v0.2 修订记录

### 10.1 三处设计错误修正

| # | v0.1 错误 | v0.2 修正 | 来源 |
|---|---|---|---|
| 1 | 把空 porcelain 归入 Git 读取失败 | 空 porcelain 为合法 clean；仅命令失败或空 HEAD 拒绝 | D2/F 回填 |
| 2 | Sampling 键暗示记录 `temperature/top_p` | runner 未传这些参数，只记 `max_tokens`、默认值说明与 `llama_cpp` 版本 | F4 回填 |
| 3 | 要求 runner 循环从 guard 判定处取值 | 候选正文在 `session.py` 局部变量，scope 扩至可选只读 capture sink | F2 回填 |

### 10.2 v0.1 盲点补齐

| # | 盲点 | v0.2 补法 |
|---|---|---|
| a | Checkpoint payload 原样嵌矩阵，provenance 会破坏 AC-7 | Loader 剥离与 grep 哨兵 |
| b | 中断 resume 后 capture 丢失 | Capture 随 checkpoint 保存并聚合 |
| c | Lock/checkpoint 未忽略导致 runner 自污染 | 采集时序硬约束与 B0.5 |
| d | 单一 pattern family/verdict 无法覆盖双门出口 | 双门 decision DTO |
| e | `scenario_id+seed` 撞键 | 六元 join 键 |
| f | `git_dirty` 无法区分同 commit 不同改动 | `worktree_fingerprint` |
| g | Echo retest HEAD=`8d6cb4b` 证明 commit hash 不足 | 背景锚点与 AC-3 |
