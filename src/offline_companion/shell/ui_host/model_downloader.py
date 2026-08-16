"""模型下载器：提供可恢复、可校验且可审计的 A 层下载流程。"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from offline_companion.core.event_stream import EventStream
from offline_companion.shell.ui_host.model_registry import (
    BUILTIN_MODELS,
    ModelDirectory,
    ModelEntry,
)

logger = logging.getLogger(__name__)


class DownloadState(str, Enum):
    """摘要：模型下载生命周期状态。"""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class DownloadProgress:
    """摘要：一次模型下载的可观察进度。"""

    model_id: str
    state: DownloadState
    downloaded_bytes: int
    total_bytes: int
    speed_bytes_per_sec: float
    error: str | None
    source_url: str | None
    attempt: int
    source_index: int


class ThrottledProgressReporter:
    """摘要：按时间间隔合并下载进度回调，避免 SSE 事件洪泛。"""

    def __init__(self, callback: Callable[[DownloadProgress], None], interval: float = 0.5) -> None:
        """摘要：初始化节流报告器。"""
        self._callback = callback
        self._interval = max(0.0, float(interval))
        self._last_report = 0.0
        self._last_progress: DownloadProgress | None = None

    def report(self, progress: DownloadProgress) -> None:
        """摘要：在达到间隔或进入终态时报告最新进度。"""
        now = time.monotonic()
        if (
            self._last_progress is None
            or now - self._last_report >= self._interval
            or progress.state is not DownloadState.DOWNLOADING
        ):
            self._callback(progress)
            self._last_report = now
        self._last_progress = progress


class DownloadError(RuntimeError):
    """摘要：模型下载或完整性校验失败。"""


class DownloadCancelled(DownloadError):
    """摘要：用户取消模型下载。"""


class ModelNotFoundError(DownloadError):
    """摘要：请求的模型不在注册表中。"""


class ModelDownloader:
    """摘要：使用 urllib 实现断点续传、多源重试和 SHA256 校验。"""

    def __init__(
        self,
        registry: Iterable[ModelEntry] = BUILTIN_MODELS,
        directory: ModelDirectory | None = None,
        event_stream: EventStream | None = None,
        *,
        max_retries: int = 3,
        chunk_size: int = 1024 * 1024,
        request_timeout: float = 30.0,
        retry_backoff_base: float = 1.0,
    ) -> None:
        """摘要：初始化下载器。

        参数：
            registry: 可下载模型注册项集合。
            directory: 模型文件目录；缺省时使用当前仓库模型目录。
            event_stream: 下载审计事件目标。
            max_retries: 每个源的最大尝试次数。
            chunk_size: 单次读取的字节数。
            request_timeout: 单次 HTTP 请求超时时间。
            retry_backoff_base: 重试指数退避基数，测试可设为零。
        """
        self._registry = {entry.model_id: entry for entry in registry}
        self._directory = directory or ModelDirectory(Path.cwd())
        self._event_stream = event_stream
        self._max_retries = max(1, int(max_retries))
        self._chunk_size = max(1, int(chunk_size))
        self._request_timeout = max(0.1, float(request_timeout))
        self._retry_backoff_base = max(0.0, float(retry_backoff_base))
        self._downloads: dict[str, DownloadProgress] = {}
        self._cancel_flags: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def download(
        self,
        model_id: str,
        progress_callback: Callable[[DownloadProgress], None] | None = None,
    ) -> Path:
        """摘要：同步下载并校验指定模型，调用方应在线程中执行。

        参数：
            model_id: 注册表中的模型 ID。
            progress_callback: 每次进度变化时调用的回调。
        返回值：
            校验通过后的最终 GGUF 路径。
        Raises:
            ModelNotFoundError: 模型未注册。
            DownloadCancelled: 用户取消下载。
            DownloadError: 所有源均失败或 SHA256 校验失败。
        """
        entry = self._registry.get(model_id)
        if entry is None:
            raise ModelNotFoundError(model_id)
        with self._lock:
            current = self._downloads.get(model_id)
            if current is not None and current.state in {
                DownloadState.PENDING,
                DownloadState.DOWNLOADING,
                DownloadState.VERIFYING,
            }:
                raise DownloadError(f"模型正在下载: {model_id}")
            cancel_flag = self._cancel_flags.setdefault(model_id, threading.Event())

        final_path = self._directory.model_path(model_id)
        temp_path = final_path.with_suffix(final_path.suffix + ".tmp")
        self._directory.ensure_dir()
        total_bytes = int(entry.size_bytes)
        self._set_progress(
            DownloadProgress(
                model_id,
                DownloadState.PENDING,
                temp_path.stat().st_size if temp_path.exists() else 0,
                total_bytes,
                0.0,
                None,
                None,
                0,
                0,
            ),
            progress_callback,
        )
        last_error: Exception | None = None
        try:
            if cancel_flag.is_set():
                raise DownloadCancelled(model_id)
            for source_index, url in enumerate(entry.download_urls):
                for attempt in range(1, self._max_retries + 1):
                    try:
                        self._emit(
                            "model/download_started",
                            {"model_id": model_id, "total_bytes": total_bytes, "source_url": url},
                        )
                        self._download_from_url(
                            entry,
                            url,
                            temp_path,
                            source_index,
                            attempt,
                            cancel_flag,
                            progress_callback,
                        )
                        self._set_state(
                            model_id,
                            DownloadState.VERIFYING,
                            temp_path.stat().st_size if temp_path.exists() else 0,
                            total_bytes,
                            url,
                            attempt,
                            source_index,
                            progress_callback,
                        )
                        if not self._verify_sha256(temp_path, entry.sha256):
                            raise DownloadError("SHA256 校验失败")
                        os.replace(str(temp_path), str(final_path))
                        self._set_state(
                            model_id,
                            DownloadState.COMPLETED,
                            final_path.stat().st_size,
                            total_bytes,
                            url,
                            attempt,
                            source_index,
                            progress_callback,
                        )
                        self._emit(
                            "model/download_completed",
                            {
                                "model_id": model_id,
                                "path": str(final_path),
                                "sha256_verified": True,
                            },
                        )
                        return final_path
                    except DownloadCancelled:
                        raise
                    except (DownloadError, OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
                        last_error = exc
                        if "SHA256 校验失败" in str(exc):
                            temp_path.unlink(missing_ok=True)
                        logger.warning(
                            "模型下载失败，准备重试: model=%s source=%s attempt=%s error=%s",
                            model_id,
                            source_index,
                            attempt,
                            exc,
                        )
                        if attempt < self._max_retries:
                            time.sleep(self._retry_backoff_base * (2 ** (attempt - 1)))
                if temp_path.exists() and last_error is not None:
                    temp_path.unlink(missing_ok=True)
            error_text = str(last_error or "没有可用下载源")
            self._set_failed(model_id, error_text, progress_callback)
            self._emit(
                "model/download_failed",
                {"model_id": model_id, "error": error_text, "attempted_sources": list(entry.download_urls)},
            )
            raise DownloadError(f"所有下载源均失败: {error_text}") from last_error
        except DownloadCancelled:
            partial_bytes = temp_path.stat().st_size if temp_path.exists() else 0
            self._set_state(
                model_id,
                DownloadState.CANCELLED,
                partial_bytes,
                total_bytes,
                None,
                0,
                0,
                progress_callback,
            )
            self._emit("model/download_cancelled", {"model_id": model_id, "partial_bytes": partial_bytes})
            raise
        finally:
            with self._lock:
                self._cancel_flags.pop(model_id, None)

    def cancel(self, model_id: str) -> None:
        """摘要：设置指定模型的取消标志。"""
        with self._lock:
            flag = self._cancel_flags.setdefault(model_id, threading.Event())
            flag.set()

    def get_progress(self, model_id: str) -> DownloadProgress | None:
        """摘要：返回指定模型最近一次下载进度。"""
        with self._lock:
            return self._downloads.get(model_id)

    def verify_local_model(self, model_id: str, path: Path | None = None) -> bool:
        """摘要：校验本地模型文件并写入完整性事件。

        参数：
            model_id: 注册表中的模型 ID。
            path: 待校验路径；省略时使用模型目录中的标准路径。
        返回值：
            SHA256 校验通过返回 True，否则返回 False。
        Raises:
            ModelNotFoundError: 模型未注册。
        """
        entry = self._registry.get(model_id)
        if entry is None:
            raise ModelNotFoundError(model_id)
        model_path = path or self._directory.model_path(model_id)
        actual_sha256 = self._sha256(model_path)
        if actual_sha256 is not None and actual_sha256.lower() == entry.sha256.lower():
            self._emit("model/verified", {"model_id": model_id, "sha256_ok": True})
            return True
        self._emit(
            "model/verification_failed",
            {
                "model_id": model_id,
                "expected": entry.sha256,
                "actual": actual_sha256,
                "path": str(model_path),
            },
        )
        return False

    def _download_from_url(
        self,
        entry: ModelEntry,
        url: str,
        destination: Path,
        source_index: int,
        attempt: int,
        cancel_flag: threading.Event,
        progress_callback: Callable[[DownloadProgress], None] | None,
    ) -> None:
        existing_size = destination.stat().st_size if destination.exists() else 0
        headers = {"Range": f"bytes={existing_size}-"} if existing_size else {}
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=self._request_timeout) as response:
            status_value = getattr(response, "status", None)
            status = int(status_value if status_value is not None else response.getcode())
            content_length = int(response.headers.get("Content-Length") or 0)
            if status == 206 and existing_size:
                mode = "ab"
                downloaded = existing_size
            elif status == 200:
                mode = "wb"
                downloaded = 0
            else:
                raise DownloadError(f"下载服务器返回状态码: {status}")
            total_bytes = int(entry.size_bytes or (downloaded + content_length))
            started_at = time.monotonic()
            self._set_state(
                entry.model_id,
                DownloadState.DOWNLOADING,
                downloaded,
                total_bytes,
                url,
                attempt,
                source_index,
                progress_callback,
            )
            with destination.open(mode) as handle:
                while True:
                    if cancel_flag.is_set():
                        raise DownloadCancelled(entry.model_id)
                    chunk = response.read(self._chunk_size)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(time.monotonic() - started_at, 1e-6)
                    progress = self._set_state(
                        entry.model_id,
                        DownloadState.DOWNLOADING,
                        downloaded,
                        total_bytes,
                        url,
                        attempt,
                        source_index,
                        progress_callback,
                        speed=downloaded / elapsed,
                    )
                    self._emit(
                        "model/download_progress",
                        {
                            "model_id": entry.model_id,
                            "downloaded_bytes": progress.downloaded_bytes,
                            "total_bytes": progress.total_bytes,
                            "speed": progress.speed_bytes_per_sec,
                            "attempt": attempt,
                            "source_index": source_index,
                        },
                    )

    @staticmethod
    def _verify_sha256(path: Path, expected: str) -> bool:
        """摘要：分块计算文件 SHA256，不将模型整体读入内存。"""
        actual = ModelDownloader._sha256(path)
        return bool(actual and expected and actual.lower() == expected.lower())

    @staticmethod
    def _sha256(path: Path) -> str | None:
        """摘要：分块计算文件 SHA256，文件不存在时返回 None。"""
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _set_failed(
        self,
        model_id: str,
        error: str,
        progress_callback: Callable[[DownloadProgress], None] | None,
    ) -> None:
        current = self.get_progress(model_id)
        self._set_state(
            model_id,
            DownloadState.FAILED,
            current.downloaded_bytes if current else 0,
            current.total_bytes if current else 0,
            current.source_url if current else None,
            current.attempt if current else 0,
            current.source_index if current else 0,
            progress_callback,
            error=error,
        )

    def _set_state(
        self,
        model_id: str,
        state: DownloadState,
        downloaded_bytes: int,
        total_bytes: int,
        source_url: str | None,
        attempt: int,
        source_index: int,
        progress_callback: Callable[[DownloadProgress], None] | None,
        *,
        speed: float = 0.0,
        error: str | None = None,
    ) -> DownloadProgress:
        progress = DownloadProgress(
            model_id,
            state,
            downloaded_bytes,
            total_bytes,
            speed,
            error,
            source_url,
            attempt,
            source_index,
        )
        self._set_progress(progress, progress_callback)
        return progress

    def _set_progress(
        self,
        progress: DownloadProgress,
        progress_callback: Callable[[DownloadProgress], None] | None,
    ) -> None:
        with self._lock:
            self._downloads[progress.model_id] = progress
        if progress_callback is not None:
            progress_callback(progress)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._event_stream is not None:
            self._event_stream.append(event_type, payload)
