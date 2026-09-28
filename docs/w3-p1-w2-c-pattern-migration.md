# W3-P1 W2-C 模式迁移对照表

日期：2026-09-25  
状态：P1-1 实现资产  
权威目标：`configs/persona_constraint_l4_patterns.yaml` 的 `identity_cliff`

| W2-C 原模式 | L4 归属 | 迁移结果 |
| --- | --- | --- |
| `作为…AI/人工智能`、`我是…AI/人工智能` | `identity_cliff.generic_ai_self_reference` | 既有 family 保持不变 |
| `作为…语言模型/智能助手/机器人/助手`、`我（只）是…语言模型/程序/机器人/助手` | `identity_cliff.generic_model_self_reference` | 新 family 排在 `identity_reset` 之后，保留既有首匹配归因；带显示名 guard 与“设定仍生效”排除 |
| `我没有…性格/个性/感情/意识/自我` | `identity_cliff.persona_role_denial` | 既有模式已覆盖，不重复写入 |
| `我（只）能提供/回答信息/知识/帮助` | `identity_cliff.generic_assistant_limitation` | 新增 family，带 `requires_display_name_absent` |
| `我不是/没有真实的人/人类` | `identity_cliff.generic_assistant_limitation` | 新增 family，带 `requires_display_name_absent` |

迁移纪律：不新增 zone，不改变 `identity_cliff` 的 `retry_then_fallback` 动作；显示名完整出现时，两个通用自述 family 均放行。旧 C 臂检测器、重试和确定性 fallback 不再作为运行时权威。
