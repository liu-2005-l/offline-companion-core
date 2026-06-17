"""errors：跨层异常类型（中文说明遵循项目文档字符串规范）。"""


class BundleFormatError(ValueError):
    """摘要：导出包格式非法或缺少必需条目。

    说明：由 C2 在读取 ZIP/manifest 失败时抛出；调用方应提示用户文件损坏或版本不兼容。
    """


class ConsentArtifactError(ValueError):
    """摘要：Consent Artifact 未通过 A3 侧结构校验。

    说明：在写入 C2 审计表之前由 `validate_consent_artifact` 抛出；携带可读原因便于日志与 UI。
    """


class OutboundDenied(RuntimeError):
    """摘要：当前隐私策略或用户选择不允许出站。"""


class InferenceBackendError(RuntimeError):
    """摘要：本地推理后端不可用（路径、依赖或加载失败）。

    说明：由 C1 在 health_check 或构造 LlamaCppBackend 失败时抛出。
    """


class ReformatError(ValueError):
    """摘要：B4 规则润色无法安全处理云端原文。

    说明：编排层应触发本地硬降级，不得将未润色云端原文直接呈现用户。
    """


class CloudConnectorError(RuntimeError):
    """摘要：A3 出站 HTTP 调用失败（配置、网络或响应格式）。"""


class SkillManifestError(ValueError):
    """摘要：Skill manifest 未通过 Schema 或 registry 语义校验。"""


class SkillPolicyDenied(RuntimeError):
    """摘要：当前隐私模式或策略不允许启用/调用该 Skill。"""
