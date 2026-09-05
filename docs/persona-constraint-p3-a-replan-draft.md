# 人格约束 P3-A 重规划骨架

版本：v0.3（P3-0 `no_effect` 终局与 A1 schema trace 修订稿）

状态：待本地规格锚；锚定后按 A1→A5 严格串行执行

上游：`docs/persona-constraint-p3-wiring-spec-draft.md`、
`docs/persona-constraint-p3-0-l2-no-effect-closure-spec.md`、P3-0 锚 `74a8144`

## 0. 范围总纲

- 删除 L2 解码参数数值包接线，不新增人格采样 DTO，不改 `GenerationOptions` schema；
- 保留 L1 文本组装、L3 触发谓词、L4 冻结 retry/fallback 与 persona 持久化基座；
- 运行时数据流固定为 `signals → L3 判定 → L1 样本选择/低强度 profile → L4`；
- 实现可先搭 L1 再接 L3，施工顺序不得被写成运行时数据流；
- `no_effect_observed_within_preregistered_grid` 只约束当前模型与预注册网格，未来翻案必须另锚实验。

## 1. A1：持久化基座与假成功修复

### 1.1 三层事实源

- `sessions.persona_id + persona_snapshot_*` 是会话人格事实源；
- `personas.active` 只表示下一新会话默认人格，复用既有部分唯一索引；
- `settings.json` 的 `active_persona_id/active_session_id` 只能作为可重建投影，不参与运行时判定。

会话快照直接内联 `sessions`，每会话一份、不跨会话去重。快照保存创建时刻的最终有效 system prompt、
规范化 OCEAN、档位、展示身份、验证状态与人格约束资产 provenance，使旧会话无需按新版映射反推。

### 1.2 canonical session

新增类型化单例表 `desktop_session_state`，以 `TEXT` 外键指向 `sessions.id`，并维护单调递增 `revision`。
不使用无外键的 KV，也不在所有历史 session 上增加 `is_canonical`。

### 1.3 原子切换

切换请求携带 `switch_request_id + expected_revision`。服务端以非阻塞切换锁保证单飞；并发第二请求或存在进行中
turn/计划写入时返回 409 且零状态变化。事务使用显式 `BEGIN IMMEDIATE`，因为仓库连接以
`isolation_level=None` 打开，普通 `with conn` 不能承担本批三写原子性。

同一事务完成：

1. 校验 target persona 与 expected revision；
2. 构造并校验 canonical snapshot；
3. 新建 session 并写内联快照与幂等键；
4. 更新 `personas.active` 的下一会话默认语义；
5. 更新 `desktop_session_state.active_session_id/revision`。

提交前失败整体回滚。提交后仅执行一次已预构造、不可抛错的 `DesktopSessionContext` 指针替换；若发生不可恢复的
提交后异常，运行时进入禁发状态并要求重启，不允许继续以旧 context 服务。重启从 SQLite canonical 恢复。

### 1.4 前端四象限

- 2xx 且 request/session/revision/snapshot 字段完整：更新 UI；
- 明确的提交前语义失败且响应声明 `state_unchanged=true`：保留旧 UI 并报错；
- timeout、网络断开、响应损坏或未声明状态不变的 5xx：进入对账态，禁止发消息；
- 对账读取 SQLite canonical：按实际 session 更新 UI，补齐“已提交但响应丢失”的假失败窗口。

现有 `shell_api.js` 的 catch 分支不得调用 `localActivate()`。`settings.json` 投影只能在 canonical 对账成功后更新。

### 1.5 A1 验收

A1 以 `docs/persona-constraint-p3-a1-persistence-spec-draft.md` 的 T1–T11、迁移矩阵、真实子进程重启探针和
context 重绑定断言为门槛。前端假成功修复属于 A1，不顺延 A5。

## 2. A2：L1 文本组装与资产补全

- 复用 `883f84b` 冻结机械映射；
- 建立 3 类 × 5 人格共 15 条确定性文案；
- 落完整根 + SHA-256 解析，禁止跨根拼接并覆盖旧 configs 遮挡；
- 物理加入五个冻结标定预设，保留三现有人格和用户 OCEAN；
- 执行 traits 迁移三件套：导出手写标签、移除 traits 编辑入口、`tone_keywords` 分域；
- 清零 API/仓储写旁路，外部提交 traits 明确返回 `traits_read_only`；
- 实现 `hidden_after_pair_gate` 的 dormant 状态与选择函数，但 P4 verdict 在场前不得生效。

验收：同输入组装逐字节一致；15 条文案全过 lint；旧 configs 遮挡回归；五预设与自定义未验证状态可区分；
隐藏策略在 P4 前保持 inactive。

## 3. A3：L3 谓词与审计信号

- 落地 P3-0 冻结的 `PersonaTurnSignals`、阈值、非法信号、优先级与一次性消费；
- 在精确生产点注册并产生三个审计事件，EventStream 只作同源镜像；
- L3 结果驱动 L1 标准/共情低强度/纠错低强度样本选择与后置 low profile；
- 常驻 lint 及其正控进入 CI。

## 4. A4：L4 retry/fallback 基线接线

- 只接通 P1 冻结检测器与 `direct/retry/fallback/observe` 动作链；
- 人格约束会话先缓冲后检测，原始坏 token 不得流出；
- 保护区继续逐字节透传；
- 检测覆盖扩展、检测域扩展、4-gram 重校与跨轮结构改造仍归 W3。

“隐藏较弱者”不在 A4 重新裁决。其 dormant 实现随 A2 预设状态落地，P4 后才允许激活。

## 5. A5：闭合

- UX 契约端到端回归：新会话生效、历史会话恢复、失败零状态变化、超时对账；
- 全量重跑 P1/P2 静态 fixture、受影响运行时窄测与关闭路径逐字节契约；
- 回填 P3 报告、v1.5 验收与架构/CHANGELOG 文档；
- 不重跑 P1/P2 原始 GGUF 实验，不用旧 artifact 冒充新接线验证。

## 6. 债务映射

| 债务 | 状态 | 落点 |
| --- | --- | --- |
| persona 切换 UX 契约 | 已裁 | A1 实现，A5 端到端回归 |
| 审计事件白名单注册 | 待执行 | A3 |
| 隐藏较弱者 | 已裁、不重裁 | A2 dormant 实现，P4 verdict 后激活 |
| fixture 重跑义务 | 待执行 | A5 闭合门槛 |

## 7. 提交边界

各 phase 独立本地提交。用户未在当前任务明确授权远端推送时不得 `git push`。A1 不夹带 A2 资产实现，
但 schema 与快照字段必须为最终 L1 组装产物预留稳定承载面。
