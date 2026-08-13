# 1.5B 模型 Function Calling 方案

> **文档状态**：评审闭合（2026-08-13）
> **评审轮次**：3 轮，11 + 2 个问题全部解决
> **架构归属**：C1 推理层 + A2 ToolInvoker 层 + PlanOrchestrator 层
> **核心原则**：工程约束为主，轻量微调为辅，用架构设计抵消模型能力短板
> **实现状态**：方案阶段；当前本地 Backend 与 Subagent 生产 adapter 尚未透传 grammar/tool calls

---

## 一、定位

### 1.1 问题

1.5B 量级小模型（Qwen2.5-1.5B-Instruct）不适合靠原生能力硬扛 function calling——参数规模使多工具选择、稳定格式和参数完整性更具挑战。具体格式合格率必须由本项目固定测试集实测，本文不把外部经验值当作当前基线。

### 1.2 核心思路

**工程约束为主，轻量微调为辅，用架构设计抵消模型能力短板**。所有方案兼容 llama.cpp + GGUF 本地部署，可直接嵌入现有 A/B/C 分层架构。

### 1.3 三层递进

| 层级 | 手段 | 目标 | 周期 |
|------|------|------|------|
| P0 | 纯工程约束（GBNF + Prompt + 校验） | 显著降低格式错误并建立可测基线 | 预估 1-2 天 |
| P1 | 语义召回升级 + LoRA 微调 | 提升工具选择准确率 | 预估 3-5 天 |
| P2 | 双模型分工（可选） | 工具选择完全不占用 LLM 算力 | 远期 |

---

## 二、P0：零训练纯工程方案

### 2.1 llama.cpp GBNF 文法约束——根治格式错误

**外部能力前提**：目标版本的 llama-server `/completion` 与 `/v1/chat/completions` 需要支持 `grammar` 请求字段；`llama-cpp-python` 需要支持 grammar 对象或等价 JSON Schema 约束。仓库当前 vendored sidecar 版本、Python binding 版本和实际请求字段尚未形成 smoke 证据，因此 P0 第一项必须做双后端能力探测，不能仅凭版本假定可用。

**验证方式**：

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"local","messages":[{"role":"user","content":"调用工具查询当前时间"}],"grammar":"root ::= \"{\\\"name\\\":\\\"datetime_now\\\",\\\"parameters\\\":{} }\""}'
```

上述命令只用于 sidecar 能力 smoke；正式测试应由 pytest 构造 JSON 请求，避免 shell 转义差异被误判为 grammar 不支持。

**适配 1.5B 的关键设计**：

- 不做复杂嵌套文法，只做扁平化单工具调用文法
- 一次只允许调用 1 个工具，避免模型算力不够还硬输出多工具导致乱码
- 参数全部扁平化，复杂结构拆成多个步骤调用

**集成位置**：C1 的统一 `InferenceBackend` 生成接口新增可选约束参数，由 `LlamaCppBackend` 和 `LlamaServerBackend` 分别适配；A2 工具选择协调器根据候选工具生成 GBNF，再通过注入的 Backend adapter 发起推理。`ToolInvoker` 只负责已选工具的权限、参数校验、Consent 和执行，不负责调用模型或直接依赖 C1 后端。

### 2.2 GBNF 规则设计

#### 2.2.1 基本结构

```
root ::= "{" ws "\"name\"" ws ":" ws tool_name ws "," ws "\"parameters\"" ws ":" ws params "}" ws
tool_name ::= "\"datetime_now\"" | "\"file_read\"" | "\"none\""
params ::= "{" [param_pairs] "}"
param_pairs ::= param_pair ("," ws param_pair)*
param_pair ::= "\"" [a-zA-Z0-9_]+ "\"" ws ":" ws string_value
```

#### 2.2.2 `none` 分支——工具调用的退路

在 `tool_name` 枚举末尾自动追加 `"none"`，让模型有"不调用工具"的退路：

- **强制约定**：`none` 工具的 `parameters` 固定为空对象 `{}`
- **注入方式**：`tool_schema_to_gbnf()` 生成文法时自动追加，无需手动声明
- **设计原则**：不靠 Prompt 提醒"不需要就说 none"，而是放进文法硬约束——1.5B 模型容易漏看 Prompt 里的可选分支，但文法是 token 级强制

#### 2.2.3 `none` 空参数的分层校验

GBNF 无法实现"字段值依赖字段名"的条件语义约束。分层方案：

| 层 | 职责 | 说明 |
|----|------|------|
| GBNF 文法层 | 保证 JSON 结构合法 | 不限制 none 的参数字段值 |
| A2 ToolCallValidator | 保证业务语义合法 | `none` 的 parameters 非空 → 触发纠错重试 |

**校验位置**：新增推理前 `ToolCallValidator`，在 `ToolInvoker.execute()` 之前按 `ToolManifest.params_schema` 校验工具名、必填字段、参数类型和值域。不能放进 `PlanGateway.verify_post_execution()`：后者校验的是步骤已经执行后的产出/evidence，放在那里会导致非法参数先执行再发现。

**纠错 Prompt 模板**：`none 工具不接受任何参数，请输出 {"name": "none", "parameters": {}}`

### 2.3 极简强约束 Prompt 模板——降低模型认知负担

1.5B 上下文承载弱，Prompt 遵循三条铁律：

1. **工具描述 ≤ 1 句话**：只说"做什么"，不说"怎么做"
2. **参数描述 ≤ 5 个 token**：只说参数名和类型，不说取值范围（交给 GBNF）
3. **单次上下文中工具 ≤ 3 个**：BM25 Top2 + 1 个 none = 3

### 2.4 BM25 工具语义召回——零模型依赖

P0 阶段用 BM25 做工具语义召回，不引入额外模型：

| 步骤 | 说明 |
|------|------|
| 索引 | 每个工具的 name + description 做 BM25 索引 |
| 召回 | 用户输入 → BM25 得分排序 → 取 Top2 |
| 阈值粗筛 | BM25 得分 < 极低阈值 → 不走工具链路，纯对话 |

### 2.5 三级过滤链路

```
BM25 极低阈值粗筛（只拦完全不沾边的）
  → GBNF 文法内模型自主选择（tool_a | tool_b | none）
    → 关键词强触发兜底（命中核心词但选 none → 1 次纠错重试）
```

**关键词强触发兜底**：

- 仅当模型输出 `name="none"` 时才执行关键词匹配
- 命中某工具的 trigger_keywords 且模型选 none → 追加纠错 Prompt 重试 1 次
- 重试后仍选 none → 尊重模型判断，降级为纯对话，不无限循环

**trigger_keywords 声明位置**：`shared.types.ToolManifest` 新增强类型字段，使用不可变 tuple 与现有 frozen dataclass 风格一致，默认空 tuple 兼容存量：

```python
@dataclass
class ToolManifest:
    # ... 现有字段 ...
    trigger_keywords: tuple[str, ...] = ()
```

**匹配逻辑**：小写归一化，命中任意一个关键词即触发。正常输出工具名时不触发，不增加正常链路开销。

**双场景适配**：

| 场景 | 匹配文本 |
|------|---------|
| 对话场景 | 用户原始输入文本 |
| Plan Step 场景 | `step.description` 字段 |

### 2.6 单步单工具约束——双保险

| 层 | 约束 | 说明 |
|----|------|------|
| Decomposer schema | `tool_id` 为可选单值 | LLM 拆解时每个 step 最多声明 1 个工具 |
| PlanStep 强类型 | 新增 `tool_id: str | None` | 快照序列化并兼容旧快照缺失字段 |
| ToolInvoker 执行层 | 每次只接收一个 `tool_id` | 接口形态天然不接受工具数组 |

复杂任务由 PlanOrchestrator 拆成单步串行调用，每次只让模型处理一个工具。

当前 `PlanStep` 只有 `skill_id`，没有 `tools` 或 `tool_id`；实现时不得把工具列表塞进自由 `payload` 形成第二套事实源。

### 2.7 复用 C-2 框架的工具合法性校验

三层校验串行，计数隔离，不交叉触发：

| 层次 | 校验内容 | 失败处理 | 计数 |
|------|---------|---------|------|
| 第 1 层：GBNF 文法 | JSON 格式、字段名、工具名枚举 | 不可能失败（token 级硬约束） | — |
| 第 2 层：A2 ToolCallValidator | 参数类型、值域、必填字段、none 空参数 | 纠错 Prompt 重试 1 次 | 工具级纠错配额 |
| 第 3 层：C-2 通用质量校验 | 产出质量、evidence 完整性、stage 规范 | feedback 重试 1 次 | quality_retry_counts |

第 2 层重试不消耗第 3 层的 `quality_retry_counts`，第 3 层重试不触发第 2 层的重新校验。

---

## 三、P1：效果进阶

### 3.1 ONNX MiniLM embedding 升级工具召回

P0 的 BM25 在短文本（工具名 + 一句话描述）上语义区分度可能不足。P1 用 ONNX MiniLM 替代：

- 模型：paraphrase-multilingual-MiniLM-L12-v2（ONNX 格式）
- 归属：模型推理与 embedding 执行在 C 层；A2 只消费候选工具排序结果。`onnxruntime + tokenizers` 已是项目依赖，但模型文件、下载策略和本地缓存仍需单独设计
- 用途：工具 description → embedding → 余弦相似度匹配用户输入

### 3.2 LoRA 微调

**训练数据生成**：

| 路径 | 说明 | 成本 |
|------|------|------|
| 云端 API 生成 | 调用大模型 API 生成 500-2000 条 function calling 样本 | 一次性，几块钱 |
| 服务器蒸馏 | GPU 服务器跑 7B 模型蒸馏 | 需要 GPU 服务器访问权 |

数据分布：单工具正常调用 70% + 闲聊（选 none）20% + 边界纠错 10%。

**微调配置**：

| 参数 | 值 | 说明 |
|------|-----|------|
| LoRA rank | 8-16 | 只微调注意力层 |
| 目标 | q_proj, v_proj | 最小参数量 |
| Epochs | 3-5 | 小数据集 |
| 预期显存 | 4-6GB | 1.5B 模型 + LoRA |

**加载方式**：llama-server `--lora` 参数启动时加载。运行时不切换（启动时固定），不需要时重启不带 LoRA。

**能力偏移风险**：LoRA 微调后对话能力可能受影响。需 A/B 测试——同一 prompt 加载 LoRA 前后的对话质量对比。

### 3.3 Subagent 链路复用

Subagent 的 RestrictedToolRegistry 输出工具白名单 → 公共 GBNF 生成器 → 随推理请求传入。重试计入 max_llm_calls 预算。

三个场景统一复用同一套文法生成与处理逻辑：

| 场景 | 候选项 |
|------|--------|
| 对话级工具调用 | 候选工具 + none，三选一 |
| Plan Step 执行 | 步骤对应工具 + none，二选一 |
| Subagent 受限工具集 | 受限工具清单 + none，模型自主判断 |

---

## 四、P2：远期优化（可选）

### 4.1 双模型分工

用轻量分类模型（如 TinyBERT）做"工具选择 / 不调用"二分类，1.5B 只负责参数填充。

- 工具选择不占用 LLM 上下文和算力
- 延迟更低，准确率更稳
- 模型权重自己训练或预训练
- 训练数据成本比 LoRA 还高
- **非必需，P0+P1 足够覆盖桌面场景**

### 4.2 LoRA 双实例路由

显存充足时，LoRA 实例和原始实例并行运行，按场景路由。

---

## 五、GBNF 规则生成

### 5.1 公共生成函数

```python
def tool_schema_to_gbnf(tools: list[ToolManifest]) -> str:
    """从工具 manifest 列表生成 GBNF 文法字符串。

    自动在 tool_name 枚举末尾追加 "none"。
    只处理扁平化参数（字符串/数字/布尔），不支持嵌套。
    """
    # 1. 根规则固定为包含 name 和 parameters 的 JSON 对象
    # 2. name 字段的值为传入工具名枚举 + "none"
    # 3. parameters 按每个参数类型生成对应文法规则
    # 4. 字符串参数可附加正则约束
```

### 5.2 维护成本

- 工具变更只改 manifest
- GBNF 自动生成
- 无额外维护工作量
- 开源参考：`jsonschema-to-gbnf` Python 实现，适配扁平化场景只需十几行代码

---

## 六、与现有架构的集成位置

| 层 | 改动 | 说明 |
|----|------|------|
| C1 推理层 | 统一 Backend 生成选项 + 双本地后端 grammar 适配 | 推理时动态传入 GBNF 字符串 |
| A2 工具选择协调器 | 召回、约束生成、模型选择、纠错重试与降级 | 与只负责执行的 ToolInvoker 分离 |
| A2 ToolCallValidator | 工具名与参数合法性校验 | 执行前拦截，复用独立工具纠错配额 |
| PlanGateway | 保持步骤执行后质量/evidence 校验 | 不承担工具参数前置校验 |
| PlanOrchestrator | decomposer schema 新增可选单值 `tool_id` | 拆解时约束单步单工具 |
| ToolManifest | 新增 `trigger_keywords: tuple[str, ...]` | 默认空 tuple，兼容存量 |
| Subagent | RestrictedToolRegistry → GBNF 生成器 | 复用同一套文法逻辑 |

---

## 七、1.5B Function Calling 避坑准则

| 准则 | 说明 |
|------|------|
| 绝不追求并行多工具调用 | 串行一步步调用，每次一个工具；提升幅度以本项目评测为准 |
| 绝不做嵌套参数工具 | 参数全部扁平化，复杂结构拆成多个步骤 |
| 绝不依赖纯 Prompt 兜底 | 必须加文法 / 后处理的外部约束 |
| 必须有降级路径 | 工具调用失败自动回退纯对话，不能让链路卡死 |

---

## 八、可观测性

| 指标 | 用途 |
|------|------|
| 进入工具链路的请求中，模型选 none 的比例 | 反向优化 BM25 阈值和工具描述 |
| 第 2 层纠错重试触发率 | 评估 GBNF + Prompt 的有效性 |
| 第 3 层质量重试触发率 | 评估工具产出质量 |
| 工具调用成功率（按工具分） | 识别哪些工具的 description 需要优化 |
| LoRA 加载前后对话质量对比 | 监控微调副作用 |

P0 验收先冻结一套至少覆盖“正确工具 / none / 歧义 / 缺参 / 非法参数 / 强触发纠错”的本地样本集，分别记录格式合法率、工具选择准确率、参数通过率、纠错后成功率和 P95 延迟。文中所有目标百分比只有在该评测集上复现后才能标记闭合。

---

## 附录：评审决策记录

### 评审过程

- **轮次 1**：11 个问题，覆盖 GBNF + llama-server 可行性、embedding 选型、C-2 关系、subagent 集成、LoRA 工程现实、双模型分工、GBNF 动态生成
- **轮次 2**：2 个问题，none 分支显式化 + 空参数校验分层 + trigger_keywords manifest 化
- **轮次 3**：LoRA 数据生成路径确认（云端 API / 服务器蒸馏，不在本机跑）

### 关键决策

1. **GBNF + llama-server 原生支持**：P0 核心前提成立，无需改架构或回退 Python 绑定
2. **三层校验串行不交叉**：GBNF 硬约束 → A2 ToolCallValidator → C-2 通用质量，计数隔离
3. **单步单工具双保险**：decomposer schema 的单值 `tool_id` + ToolInvoker 单工具接口
4. **none 分支归入 P0**：文法生成函数自动注入，校验层拦截非空参数，总代码量 < 20 行
5. **BM25 阈值从硬开关降级为粗筛**：GBNF 文法内模型自主选择 + 关键词强触发兜底，解决假阳/假阴
6. **LoRA 数据不在本机生成**：云端 API 或服务器蒸馏，不持续依赖云端

---

> **最后更新**：2026-08-13
> **评审人**：Liu Jiarong
> **状态**：P0 方案可进入实现阶段，P1/P2 按需推进
