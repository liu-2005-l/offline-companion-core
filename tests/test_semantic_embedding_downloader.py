from __future__ import annotations

import hashlib

from offline_companion.shell.ui_host.semantic_embedding_downloader import (
    SemanticEmbeddingAsset,
    SemanticEmbeddingDownloader,
)


class _Response:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self._body = body
        self.status = status
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._body)
        body, self._body = self._body[:size], self._body[size:]
        return body


def test_semantic_embedding_downloader_writes_assets_atomically(tmp_path, monkeypatch) -> None:
    """摘要：semantic embedding 下载器按资产清单落盘并校验 SHA256。"""
    model = b"onnx"
    tokenizer = b"tokenizer"
    assets = (
        SemanticEmbeddingAsset(
            "model.onnx",
            len(model),
            hashlib.sha256(model).hexdigest(),
            ("https://example.test/model.onnx",),
        ),
        SemanticEmbeddingAsset(
            "tokenizer.json",
            len(tokenizer),
            "",
            ("https://example.test/tokenizer.json",),
        ),
    )

    def open_url(request, **_kwargs):
        if request.full_url.endswith("model.onnx"):
            return _Response(model)
        return _Response(tokenizer)

    monkeypatch.setattr("urllib.request.urlopen", open_url)
    progress: list[tuple[str, int, int]] = []
    downloader = SemanticEmbeddingDownloader(data_root=tmp_path, assets=assets, chunk_size=3)

    result = downloader.download(lambda file_name, done, total: progress.append((file_name, done, total)))

    assert (result.model_dir / "model.onnx").read_bytes() == model
    assert (result.model_dir / "tokenizer.json").read_bytes() == tokenizer
    assert result.sha256_verified == ("model.onnx",)
    assert downloader.is_downloaded()
    assert not list(result.model_dir.glob("*.tmp"))
    assert progress


def test_semantic_embedding_downloader_rejects_bad_sha(tmp_path, monkeypatch) -> None:
    """摘要：ONNX 资产 SHA256 不匹配时不留下最终文件。"""
    asset = SemanticEmbeddingAsset(
        "model.onnx",
        4,
        "0" * 64,
        ("https://example.test/model.onnx",),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response(b"onnx"))
    downloader = SemanticEmbeddingDownloader(data_root=tmp_path, assets=(asset,))

    try:
        downloader.download()
    except RuntimeError as exc:
        assert "下载失败" in str(exc)
    else:
        raise AssertionError("bad sha should fail")

    assert not (downloader.model_dir / "model.onnx").exists()
