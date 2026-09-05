# 人格约束 P3-A1 持久化基座实现规格

版本：v0.3（D1–D4 裁决、repo schema trace 与网络不确定性修订稿）

状态：待本地规格锚；锚定后开工 A1

上游：`docs/persona-constraint-p3-a-replan-draft.md`、
`docs/persona-constraint-p3-wiring-spec-draft.md` §9、P3-0 锚 `74a8144`

## 0. 范围

A1 交付 SQLite canonical session、会话内联人格快照、显式原子切换事务、不可变
`DesktopSessionContext`、前端假成功修复及进程重启恢复。A1 不实现 L1/L3/L4 内容逻辑，但快照必须能冻结 A2
最终组装的 system prompt，context provider 必须能承接后续 L3/L4。

## 1. Schema 与迁移

当前 `sessions.id` 为 `TEXT`，时间戳为 Unix 秒 `REAL`，因此新增 schema 必须保持同型。数据库版本从 12 升到 13。

### 1.1 `sessions` 新列

```sql
ALTER TABLE sessions ADD COLUMN persona_snapshot_json TEXT;
ALTER TABLE sessions ADD COLUMN persona_snapshot_schema INTEGER;
ALTER TABLE sessions ADD COLUMN persona_snapshot_sha256 TEXT;
ALTER TABLE sessions ADD COLUMN persona_snapshot_source TEXT;
ALTER TABLE sessions ADD COLUMN switch_request_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_switch_request_id
ON sessions(switch_request_id)
WHERE switch_request_id IS NOT NULL;
```

- 每个 session 独占一份不可变快照，不建 `persona_snapshots` 表，不跨会话去重；
- `persona_snapshot_schema` 是快照结构版本，不是 persona 编辑次数；
- `switch_request_id` 持久化幂等事实，不能只放进程内集合；
- 新 session 五列均须完整；迁移前旧 session 可暂时为空，由迁移矩阵决定是否可恢复。

### 1.2 `desktop_session_state`

```sql
CREATE TABLE IF NOT EXISTS desktop_session_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at REAL NOT NULL
);
```

该表最多一行。迁移阶段只建表；bootstrap 确认或创建首个可恢复 session 后才插入单例行。删除 canonical session
必须先显式绑定其他 session，不能依赖级联或置空。

### 1.3 默认人格

复用现有 `personas.active` 与 `idx_personas_single_active`，不新增 `is_default`。其语义改为“下一新会话默认人格”。
当前 session 的 persona 只从 session 快照恢复。

### 1.4 旧库迁移矩阵

| 旧状态 | 迁移动作 | 恢复能力 |
| --- | --- | --- |
| session 的 persona 仍存在 | 以当前 persona 构造 `legacy_backfill` 快照并记录 hash | 可恢复，但 provenance 明示非创建时原件 |
| session 的 persona 已不存在 | 四快照列保持空 | 仅查看历史；继续聊天返回 `persona_snapshot_missing` |
| settings 投影指向有效 session | 可作为一次性迁移 hint 写 canonical | 写入后 settings 失去事实源地位 |
| settings 投影无效或为空 | 选最近更新且快照有效的 session；没有则按默认 persona 新建 | 结果写入 SQLite canonical |

迁移不得用全局 active persona 静默填补孤儿 session，也不得把 `legacy_backfill` 标成原始快照。

## 2. 快照契约

`persona_snapshot_json` 使用 UTF-8、键排序、紧凑分隔符的 canonical JSON；SHA-256 对实际持久化 UTF-8 字节计算。
读取时 schema、JSON 与 hash 任一不符均返回 `persona_snapshot_invalid`，不得回退当前 persona。

快照 schema v1 至少包含：

- `persona_id/name/default_companion_display_name/companion_display_name`；
- `role_lock/memory_default_on`；
- 规范化 OCEAN 数组与 O/C/E/A/N 档位；
- `validation_status/validated_anchor_id`；
- `effective_system_prompt` 原文；
- 人格约束 manifest 版本与 SHA-256；未接 A2 时明确为 `null`，不得伪造；
- snapshot 创建时间与 source。

不得写入云 API key、settings 全量、记忆正文、当前用户输入或其他会话可变状态。

## 3. Context 与单一绑定服务

新增不可变 `DesktopSessionContext`，至少持有：

- `session_id/revision`；
- 已校验的 persona snapshot 与 `PersonaSessionCore`；
- 该 session 的 EventStream；
- 后续 turn 所需的 session-scoped provider 引用。

新增单点 `bind_desktop_session()`。`UISessionBundle`、`ConversationOrchestrator`、Auto、memory/idle、sample、Consent、
tool 与 plan publisher 不再各自保存可漂移的裸 `session_id` 或 EventStream；长生命周期对象改持 context provider。
每个 turn 开始时捕获一次 context，整个 turn 不重新读取指针。

## 4. 切换协议与显式事务

请求至少携带：

```json
{
  "target_persona_id": "persona-id",
  "switch_request_id": "client-generated-uuid",
  "expected_revision": 7
}
```

连接以 `isolation_level=None` 打开，生产实现必须显式执行 `BEGIN IMMEDIATE`，并在唯一事务 helper 中保证
`COMMIT/ROLLBACK`；禁止用普通 `with conn` 冒充事务。

顺序固定：

1. 非阻塞获取 switch lock；存在进行中 turn/计划写入或锁冲突时返回 409、`state_unchanged=true`；
2. 查询 `switch_request_id`：同 key 同 target 且对应 session 仍为 canonical 时返回首次结果并标
   `idempotent_replay=true`；同 key 不同 target 或 canonical 已前移时返回 409；
3. 校验 `expected_revision`、target persona、snapshot schema 与组装结果；
4. 预构造新 `PersonaSessionCore`、EventStream 与完整 context；
5. `BEGIN IMMEDIATE` 后再次校验 revision 与幂等键；
6. 新建 session，写快照与 request id，更新 `personas.active`，更新 canonical pointer 与 revision；
7. `COMMIT` 后执行一次不可抛错的 context 指针赋值；
8. 返回实际 canonical session 与 snapshot 证明。

提交前失败全部回滚。若 DB 已提交但发生不可预期的 context 切换异常，runtime 进入 `session_recovery_required`，
禁发消息并终止服务；不得继续用旧 context。进程重启从 SQLite canonical 与快照恢复。

## 5. API 与前端四象限

成功响应至少包含：

```json
{
  "ok": true,
  "switch_request_id": "client-generated-uuid",
  "previous_session_id": "old-session",
  "canonical_session_id": "new-session",
  "revision": 8,
  "persona_snapshot_schema": 1,
  "persona_snapshot_sha256": "...",
  "created_new_session": true,
  "idempotent_replay": false,
  "persona": {}
}
```

前端只有在 request id 匹配、canonical session 与发起前 session 不同、revision 增加、snapshot 证明完整时才更新
chip、详情和 `_currentSessionId`。幂等重放允许返回同一新 session。

只有明确的提交前失败响应且含 `state_unchanged=true + canonical_session_id + revision` 时，前端才能断言旧状态保持。
timeout、网络错误、响应解析失败、字段不完整或未声明状态不变的 5xx 一律进入 `reconciling`：禁用消息发送与再次切换，
调用 `GET /api/sessions/current`。对账成功后按 SQLite canonical 更新 UI；对账也失败时保持禁发并提供重试，不显示
“已切换”或“切换失败但旧人格仍生效”的未经证实结论。

`shell_api.js` 的 persona catch 路径必须删除 `localActivate()`；settings 投影只能在成功或对账完成后写入。

## 6. 测试矩阵

| 编号 | 断言 |
| --- | --- |
| T1 | v12→v13 迁移后列类型、索引、FK 与单例约束正确；新 session 快照五列完整 |
| T2 | 修改 settings 投影不改变 canonical session 或当前 persona |
| T3 | 修改 `personas.active` 不影响存量 session；无显式 persona 的新 session 使用新默认 |
| T4 | 在快照、新 session、默认人格、canonical 更新各注入失败，显式事务均全回滚 |
| T5 | 子进程在 DB commit 后、context swap 前被 kill；新进程从 canonical 与快照恢复 |
| T6 | persona 编辑后新建 session 得到新快照；旧 snapshot JSON/hash/prompt 逐字节不变 |
| T7 | 明确提交前失败响应使前端保留旧 UI，catch 不再本地假激活 |
| T8 | 并发第二 switch 与生成中 switch 均 409、零状态变化、无多余 session |
| T9 | 模拟响应丢失进入 reconciling；对账完成前消息发送被拒绝，完成后 UI 与 canonical 一致 |
| T10 | 同 request id 重试不双建；不同 target 复用或 canonical 已前移返回 409 |
| T11 | 切换与历史恢复后 EventStream、Auto、memory/idle、sample、Consent、tool、plan 全部读取同一 context |

附加迁移断言：孤儿 session 只读；`legacy_backfill` 不冒充原始快照；无 session 的新库可正常创建首个 canonical。

T5 必须启动真实子进程并使用磁盘 SQLite，不能用单进程 mock。T11 至少包含一次真实消息、事件与 memory 写入，
并断言全部只落新 session。

## 7. 验收行

- [ ] T1–T11 全绿；
- [ ] v12、孤儿 session、空库三类迁移 fixture 全绿；
- [ ] T5 子进程 kill/重启探针通过；
- [ ] T9 response-loss 对账与禁发硬闸通过；
- [ ] T11 session-scoped 组件无裸 ID 漂移；
- [ ] 前端失败路径不再调用 `localActivate()`，响应字段校验与 settings 投影时序固定；
- [ ] Ruff、相关窄测、SQLite integrity/FK 检查与 `git diff --check` 通过。

## 8. 裁决记录

- D1：快照内联 sessions，每会话一份，不建独立表；
- D2：使用类型化 `desktop_session_state` 单例表；
- D3：复用 `personas.active` 作为下一新会话默认人格；
- D4：单飞锁 + 409 + 持久化 `switch_request_id`，不采用后到者胜；
- repo trace：`active_session_id` 为 `TEXT`、snapshot schema 为 `INTEGER`、时间戳为 `REAL`；
- repo trace：autocommit 连接要求显式 `BEGIN IMMEDIATE`；
- 网络边界：只有可证明的提交前失败才能断言状态未变，其余失败必须 canonical 对账。
