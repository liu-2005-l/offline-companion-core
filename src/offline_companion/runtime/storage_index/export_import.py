"""export_import：导出包 ZIP 纯 IO（C2；不决定导出内容取舍）。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from offline_companion.shared.errors import BundleFormatError
from offline_companion.shared.types import BUNDLE_FORMAT, ExportBundlePayload


def write_bundle_archive(payload: ExportBundlePayload, path: Path) -> None:
    """摘要：将 B2 组装好的载荷写入 ZIP 文件。

    参数：
        payload: 导出载荷。
        path: 输出 ZIP 路径。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(payload.manifest, ensure_ascii=False, indent=2))
        z.writestr("persona.json", payload.persona_json)
        z.writestr("sessions.jsonl", payload.sessions_jsonl)
        z.writestr("messages.jsonl", payload.messages_jsonl)
        z.writestr("memory_chunks.jsonl", payload.memory_chunks_jsonl)


def read_bundle_archive(path: Path) -> ExportBundlePayload:
    """摘要：读取 ZIP 导出包并还原载荷。

    参数：
        path: ZIP 路径。

    返回值：
        `ExportBundlePayload`。

    异常：
        BundleFormatError：缺少文件或 manifest 非法。
    """
    try:
        with zipfile.ZipFile(path, "r") as z:
            try:
                manifest_raw = z.read("manifest.json").decode("utf-8")
                persona_json = z.read("persona.json").decode("utf-8")
                sessions_jsonl = z.read("sessions.jsonl").decode("utf-8")
                messages_jsonl = z.read("messages.jsonl").decode("utf-8")
                memory_chunks_jsonl = z.read("memory_chunks.jsonl").decode("utf-8")
            except KeyError as e:
                raise BundleFormatError(f"missing entry in bundle: {e}") from e
    except zipfile.BadZipFile as e:
        raise BundleFormatError("not a valid zip bundle") from e

    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as e:
        raise BundleFormatError("manifest.json is not valid JSON") from e
    if manifest.get("format") != BUNDLE_FORMAT:
        raise BundleFormatError("unknown bundle format")
    return ExportBundlePayload(
        manifest=manifest,
        persona_json=persona_json,
        sessions_jsonl=sessions_jsonl,
        messages_jsonl=messages_jsonl,
        memory_chunks_jsonl=memory_chunks_jsonl,
    )
