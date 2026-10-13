# W3 收口批 C2b / C5 evidence-first audit

日期：2026-10-13  
状态：终态。C2b 结论为“无需进一步改动”；C5 两个去向域均为“扩域（另立新批）”，不在本批扩权。

## 1. 审计边界

- C2b 只检查身份提醒当前输出面是否仍有已登记红点，不从“提醒强化”四字反推新需求。
- C5 只评估既有去向域是否覆盖历史问题，不在评估批修改 L4 或 A3 lint。
- 历史产物保留原样；本报告新增当前代码树三 seed spot check，不用历史生成结果冒充当前结果。
- C2b 与 C5 的结论彼此独立：当前生成面无红点，不等于通用检测域覆盖完整。

## 2. C2b 身份提醒 evidence-first audit

### 2.1 结构与回归证据

1. 身份提醒已经在默认同步与流式路径按 `is_identity_intent()` 注入；普通意图仍为负控，风格样本为空时不追加空区块。对应判例见 `tests/test_persona_expression_w2.py:84`、`:109`、`:129`、`:153`、`:177`。
2. 最终组装输入继续机械断言旧特征串 `滑向通用“语言模型/没有性格”腔` 缺席，并断言新正向提醒在场，见 `tests/test_persona_expression_w2.py:148`。
3. echo retest 对旧特征串保留独立负控：旧串出现一次即判红；正常 AI / 助手自称为正控，见 `tests/test_identity_reminder_echo_retest.py:17`、`:27`。

### 2.2 当前代码树生成面 spot check

归档产物：`artifacts/persona_expression/w3_closure_c2b_identity_echo_spot_check.json`。

- 代码树：`5c07c9607ea96938d5c3cca666b8707f1494dede`。
- 配置：Qwen2.5-1.5B-Instruct-Q4_K_M，seed `42 / 1337 / 2024`，`identity_reminder_mode=identity_intent`。
- provenance 如实记录 `git_dirty=true`；脏项来自两份既有未跟踪 trace ZIP，本次未改写或归档它们。
- 三 seed 均满足：旧特征串计数 `0`、新提醒在场、身份提醒已注入、含机器人 / AI / 助手类诚实自称。
- 三条回复按当前共享规则复检均为：`scan_absolute_promises=()`、`scan_mechanism_leaks=()`、L4 `direct`。
- 汇总：`3/3 passed`，未发现提示工程元话术回显、自称错位或提醒缺席。

### 2.3 C2b 终裁

三态结论：**无需进一步改动**。

理由：结构性旧串缺席断言、专用回显负控与当前树三 seed 生成抽查同向；没有形成需要新验收契约的当前红点。B-S09 已解决，不重复立项，也不借 audit 扩写提醒文案。

## 3. C5 R1 去向域覆盖评估

### 3.1 自称不一致 → L4 身份域

历史红线并不只有“泛化 AI 自称”，还包括动态自称冲突与交互能力自相矛盾：

- `我是助手一号，我叫一号`，见 `artifacts/persona_expression/w2_arm_b_matrix.json:204`；
- `我是助手一号……我不会说话，但我能理解你`，见 `artifacts/persona_expression/w2_arm_b_matrix.json:2118`。

当前 L4 `identity_cliff` 覆盖泛化 AI / 模型自称、人格或陪伴角色否认；其中泛化自称在正确 display name 已出现时按设计放行，见 `configs/persona_constraint_l4_patterns.yaml:10`。运行时已经把当前 display name 传入 L4，见 `src/offline_companion/core/persona_constraint/l4.py:132`，因此机制入口存在；但现有 family 没有比较“声明自称”与当前 display name，也没有覆盖“正在文本交互却声称不会说话”这一类动态一致性。

三态结论：**扩域（另立新批）**。

后续批最小契约：以上两条历史形态作为独立正控；“我是 AI，不过我叫助手一号”保持 `direct` 负控；不得把所有机器人 / AI 自称误拦。该扩域不阻塞 C2b 或本次 W3 收口。

### 3.2 提示泄漏 → A3 lint 机制泄漏域

专用回归已经覆盖旧特征串：组装输入要求旧串缺席，echo runner 的机械判定要求旧串零回显。因此该具体缺陷已有回归防线。

但 A3 通用 `MECHANISM_LEAK_PATTERN` 当前只覆盖 `system prompt`、系统提示词、模型参数、内部机制、哈希、schema 等显式术语，见 `src/offline_companion/core/persona_constraint/lint.py:13`；对旧特征串执行 `scan_mechanism_leaks()` 返回空元组。A3 全语料门禁扫描的是 manifest 发布语料中的 assistant 文本，见 `tests/test_persona_constraint_a3_lint.py:31`，不会自动纳入 `expression.py` 内代码生成的 near-end reminder。

三态结论：**扩域（另立新批）**。

后续批最小契约：把代码生成的用户可见提醒文案纳入明确的 lint 输入面；旧特征串及等价提示工程元话术作为独立正控；正常“我是 AI，并具体说明性格”类用户可见自述保持负控。只增加专用判例而不扩扫描输入面与规则不能闭合该缺口。

## 4. 终态对账

| 项目 | 三态结论 | 当前动作 | W3 收口影响 |
| --- | --- | --- | --- |
| C2b 身份提醒当前输出面 | 无需进一步改动 | 归档当前树三 seed spot check | 已闭合 |
| C5 自称不一致 → L4 | 扩域 | 另立动态身份一致性小批 | 不阻塞 |
| C5 提示泄漏 → A3 lint | 扩域 | 另立代码生成提醒 lint 小批 | 不阻塞 |

本报告不修改 L4、lint、提醒文案、guard 或历史 artifacts。C6 继续负责规格实现期勘误、CHANGELOG、README 导航与 W3 总结。
