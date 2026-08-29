"""下载 v1.8.0 semantic embedding ONNX 资产。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from offline_companion.shell.ui_host.semantic_embedding_downloader import (  # noqa: E402
    SemanticEmbeddingDownloader,
)


def main() -> int:
    """摘要：下载 bge-base-zh-v1.5 ONNX 语义 embedding 资产。"""
    downloader = SemanticEmbeddingDownloader()

    def report(file_name: str, downloaded: int, total: int) -> None:
        print(f"{file_name}: {downloaded}/{total}", flush=True)

    result = downloader.download(report)
    print(f"semantic embedding model_dir={result.model_dir}")
    print(f"sha256_verified={','.join(result.sha256_verified) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
