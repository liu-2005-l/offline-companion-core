"""semantic_embedding_downloader：下载并校验可选的语义 embedding ONNX 资产。"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from offline_companion.shared.runtime_paths import models_dir

logger = logging.getLogger(__name__)

SEMANTIC_EMBEDDING_MODEL_ID = "bge-base-zh-v1.5-onnx"


@dataclass(frozen=True)
class SemanticEmbeddingAsset:
    """摘要：描述一个 semantic embedding 模型文件资产。

    参数：
        file_name: 写入语义 embedding 模型目录的文件名。
        size_bytes: 预期文件大小，用于下载前空间检查。
        sha256: 可选 SHA256；为空时只做原子落盘，不声明完整性已验证。
        download_urls: 可尝试的下载源。
    """

    file_name: str
    size_bytes: int
    sha256: str
    download_urls: tuple[str, ...]


BUILTIN_SEMANTIC_EMBEDDING_ASSETS: tuple[SemanticEmbeddingAsset, ...] = (
    SemanticEmbeddingAsset(
        file_name="model.onnx",
        size_bytes=406_953_171,
        sha256="5e5619f7cca7380b824d329c157dba10bee7cc00d0c139e82fdb7906051b8e4f",
        download_urls=(
            "https://huggingface.co/Xenova/bge-base-zh-v1.5/resolve/main/onnx/model.onnx",
            "https://hf-mirror.com/Xenova/bge-base-zh-v1.5/resolve/main/onnx/model.onnx",
        ),
    ),
    SemanticEmbeddingAsset(
        file_name="tokenizer.json",
        size_bytes=429_000,
        sha256="",
        download_urls=(
            "https://huggingface.co/Xenova/bge-base-zh-v1.5/resolve/main/tokenizer.json",
            "https://hf-mirror.com/Xenova/bge-base-zh-v1.5/resolve/main/tokenizer.json",
        ),
    ),
)


@dataclass(frozen=True)
class SemanticEmbeddingDownloadResult:
    """摘要：描述一次 semantic embedding 资产下载结果。"""

    model_dir: Path
    downloaded: tuple[Path, ...]
    sha256_verified: tuple[str, ...]


class SemanticEmbeddingDownloader:
    """摘要：下载语义 embedding ONNX 资产并落盘到模型目录。

    参数：
        data_root: 可选数据根目录；缺省使用运行时模型目录。
        assets: 资产清单，测试可注入小文件。
        chunk_size: 单次读取字节数。
        request_timeout: 下载请求超时时间。
    """

    def __init__(
        self,
        *,
        data_root: Path | None = None,
        assets: Iterable[SemanticEmbeddingAsset] = BUILTIN_SEMANTIC_EMBEDDING_ASSETS,
        chunk_size: int = 1024 * 1024,
        request_timeout: float = 30.0,
    ) -> None:
        self._model_dir = models_dir(data_root_override=data_root) / "semantic-embedding"
        self._assets = tuple(assets)
        self._chunk_size = max(1, int(chunk_size))
        self._request_timeout = max(0.1, float(request_timeout))

    @property
    def model_dir(self) -> Path:
        """摘要：返回 semantic embedding 资产目录。"""
        return self._model_dir

    def is_downloaded(self) -> bool:
        """摘要：返回模型与 tokenizer 是否都已落盘。"""
        return all((self._model_dir / asset.file_name).is_file() for asset in self._assets)

    def download(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> SemanticEmbeddingDownloadResult:
        """摘要：下载全部 semantic embedding 资产。

        参数：
            progress_callback: 可选进度回调，签名为 ``(file_name, downloaded, total)``。

        返回值：
            下载目录、落盘文件与通过 SHA256 校验的文件名。
        """
        self._model_dir.mkdir(parents=True, exist_ok=True)
        required = sum(
            max(0, asset.size_bytes - self._partial_path(asset).stat().st_size)
            if self._partial_path(asset).exists()
            else asset.size_bytes
            for asset in self._assets
        )
        free = int(shutil.disk_usage(self._model_dir).free)
        if free < required:
            raise RuntimeError(f"磁盘空间不足，semantic embedding 需要至少 {required} 字节")
        downloaded: list[Path] = []
        verified: list[str] = []
        for asset in self._assets:
            path = self._download_asset(asset, progress_callback)
            downloaded.append(path)
            if asset.sha256:
                verified.append(asset.file_name)
        return SemanticEmbeddingDownloadResult(
            model_dir=self._model_dir,
            downloaded=tuple(downloaded),
            sha256_verified=tuple(verified),
        )

    def _download_asset(
        self,
        asset: SemanticEmbeddingAsset,
        progress_callback: Callable[[str, int, int], None] | None,
    ) -> Path:
        final_path = self._model_dir / asset.file_name
        if final_path.is_file() and (
            not asset.sha256 or _sha256(final_path) == asset.sha256.lower()
        ):
            return final_path
        temp_path = self._partial_path(asset)
        last_error: Exception | None = None
        for url in asset.download_urls:
            try:
                self._download_from_url(asset, url, temp_path, progress_callback)
                if asset.sha256 and _sha256(temp_path) != asset.sha256.lower():
                    temp_path.unlink(missing_ok=True)
                    raise RuntimeError(f"SHA256 校验失败: {asset.file_name}")
                os.replace(str(temp_path), str(final_path))
                return final_path
            except (OSError, RuntimeError, TimeoutError, urllib.error.URLError) as exc:
                last_error = exc
                logger.warning(
                    "semantic embedding asset download failed file=%s url=%s error=%s",
                    asset.file_name,
                    url,
                    exc,
                )
        raise RuntimeError(f"semantic embedding 资产下载失败: {asset.file_name}") from last_error

    def _download_from_url(
        self,
        asset: SemanticEmbeddingAsset,
        url: str,
        temp_path: Path,
        progress_callback: Callable[[str, int, int], None] | None,
    ) -> None:
        existing_size = temp_path.stat().st_size if temp_path.exists() else 0
        headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=self._request_timeout) as response:
            status_value = getattr(response, "status", None)
            status = int(status_value if status_value is not None else response.getcode())
            if status == 206 and existing_size:
                mode = "ab"
                downloaded = existing_size
            elif status == 200:
                mode = "wb"
                downloaded = 0
            else:
                raise RuntimeError(f"下载服务器返回状态码: {status}")
            total = int(asset.size_bytes or downloaded + int(response.headers.get("Content-Length") or 0))
            with temp_path.open(mode) as handle:
                while True:
                    chunk = response.read(self._chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback is not None:
                        progress_callback(asset.file_name, downloaded, total)

    def _partial_path(self, asset: SemanticEmbeddingAsset) -> Path:
        return self._model_dir / f"{asset.file_name}.tmp"


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
