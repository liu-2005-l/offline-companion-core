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
