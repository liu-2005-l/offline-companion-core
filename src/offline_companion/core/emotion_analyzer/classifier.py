"""classifier：B0 情绪分类器。"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from offline_companion.core.emotion_analyzer.context import EmotionContext
from offline_companion.shared.errors import (
    B0EmotionConfidenceLow,
    B0EmotionModelLoadError,
    B0EmotionTokenizerError,
)
from offline_companion.shared.runtime_paths import dev_repo_root, models_dir

try:
    import onnxruntime as ort
except ImportError:  # pragma: no cover
    ort = None

try:
    from tokenizers import Tokenizer
except ImportError:  # pragma: no cover
    Tokenizer = None

_LABELS = ("anger", "anxiety", "neutral", "joy", "sadness", "surprise", "disgust")
_VAD = {
    "anger": (-0.8, 0.9, -0.2),
    "anxiety": (-0.6, 0.8, -0.5),
    "neutral": (0.0, 0.0, 0.0),
    "joy": (0.8, 0.7, 0.6),
    "sadness": (-0.7, 0.3, -0.6),
    "surprise": (0.3, 0.8, 0.2),
    "disgust": (-0.5, 0.4, -0.3),
}
_STRATEGIES = {
    "anger": "calm_reassurance",
    "anxiety": "deep_empathy",
    "neutral": "neutral_follow",
    "joy": "joy_amplify",
    "sadness": "warm_comfort",
    "surprise": "curious_engage",
    "disgust": "gentle_redirect",
}
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(气死|烦死|受不了|忍不了|火大|怒|生气|滚开|闭嘴|可恶)"), "anger"),
    (re.compile(r"(焦虑|紧张|担心|不安|害怕|恐惧|失眠|压力大|心慌)"), "anxiety"),
    (re.compile(r"(开心|高兴|快乐|幸福|太棒|太好|喜欢|感动|满足|兴奋|哈哈)"), "joy"),
    (re.compile(r"(难过|伤心|悲伤|想哭|失落|绝望|孤独|委屈|郁闷|emo)"), "sadness"),
    (re.compile(r"(惊讶|震惊|居然|竟然|不会吧|天哪|难以置信)"), "surprise"),
    (re.compile(r"(恶心|讨厌|反感|厌恶|嫌弃|看不惯)"), "disgust"),
]


@dataclass
class RuleEmotionClassifier:
    """摘要：规则版情绪分类器，用于 B0 回退。"""

    def predict(self, text: str) -> EmotionContext:
        body = (text or "").strip()
        if not body:
            return EmotionContext()
        best_label = "neutral"
        best_hits = 0
        for pattern, label in _RULES:
            hits = len(pattern.findall(body))
            if hits > best_hits:
                best_hits = hits
                best_label = label
        confidence = min(0.95, 0.4 + 0.15 * best_hits) if best_hits else 0.0
        valence, arousal, dominance = _VAD[best_label]
        return EmotionContext(
            emotion=best_label,
            confidence=confidence,
            valence=valence,
            arousal=arousal,
            dominance=dominance,
            suggested_strategy=_STRATEGIES[best_label],
            raw={"mode": "rule", "matched_hits": best_hits},
        )


@dataclass
class EmotionClassifier:
    """摘要：ONNX 优先、规则回退的 B0 情绪分类器。"""

    model_path: Path | None = None
    tokenizer_path: Path | None = None
    confidence_threshold: float = 0.45

    def __post_init__(self) -> None:
        root = models_dir()
        self.model_path = self.model_path or self._first_existing(
            root / "emotion_classifier.onnx",
            dev_repo_root() / "fixtures" / "emotion_test_identity.onnx",
        )
        self.tokenizer_path = self.tokenizer_path or self._first_existing(
            root / "tokenizer.json",
            dev_repo_root() / "models" / "tokenizer.json",
        )
        self._rule_fallback = RuleEmotionClassifier()
        self._session = None
        self._tokenizer = None

    def predict(self, text: str) -> EmotionContext:
        body = (text or "").strip()
        if not body:
            return EmotionContext()
        try:
            context = self._predict_with_onnx(body)
            if context.confidence < self.confidence_threshold:
                raise B0EmotionConfidenceLow("情绪置信度不足，切换规则回退")
            return context
        except (B0EmotionModelLoadError, B0EmotionTokenizerError, B0EmotionConfidenceLow):
            fallback = self._rule_fallback.predict(body)
            return EmotionContext(
                emotion=fallback.emotion,
                confidence=fallback.confidence,
                valence=fallback.valence,
                arousal=fallback.arousal,
                dominance=fallback.dominance,
                suggested_strategy=fallback.suggested_strategy,
                raw={**fallback.raw, "fallback": True},
            )

    def _predict_with_onnx(self, text: str) -> EmotionContext:
        session = self._load_session()
        tokenizer = self._load_tokenizer()
        encoded = tokenizer.encode(text)
        inputs_meta = session.get_inputs()
        if not inputs_meta:
            raise B0EmotionModelLoadError("情绪模型缺少输入定义")
        input_name = inputs_meta[0].name

        import numpy as np

        if len(inputs_meta) == 1:
            values = np.array([encoded.ids or [0]], dtype=np.int64)
            outputs = session.run(None, {input_name: values})
        else:
            ids = np.array([encoded.ids or [0]], dtype=np.int64)
            mask = np.array([encoded.attention_mask or [1] * len(ids[0])], dtype=np.int64)
            feeds = {inputs_meta[0].name: ids, inputs_meta[1].name: mask}
            outputs = session.run(None, feeds)
        logits = outputs[0]
        flat = [float(x) for x in getattr(logits, "flatten", lambda: logits)()]
        if len(flat) < len(_LABELS):
            raise B0EmotionConfidenceLow("情绪模型输出维度不足，切换规则回退")
        probs = self._softmax(flat[: len(_LABELS)])
        best_idx = max(range(len(probs)), key=probs.__getitem__)
        label = _LABELS[best_idx]
        valence, arousal, dominance = _VAD[label]
        return EmotionContext(
            emotion=label,
            confidence=probs[best_idx],
            valence=valence,
            arousal=arousal,
            dominance=dominance,
            suggested_strategy=_STRATEGIES[label],
            raw={"mode": "onnx", "probabilities": dict(zip(_LABELS, probs))},
        )

    def _load_session(self):
        if self._session is not None:
            return self._session
        if ort is None or self.model_path is None or not self.model_path.is_file():
            raise B0EmotionModelLoadError("情绪 ONNX 模型不可用")
        try:
            self._session = ort.InferenceSession(str(self.model_path))
            return self._session
        except Exception as exc:  # pragma: no cover
            raise B0EmotionModelLoadError(f"情绪模型加载失败: {exc}") from exc

    def _load_tokenizer(self):
        if self._tokenizer is not None:
            return self._tokenizer
        if Tokenizer is None or self.tokenizer_path is None or not self.tokenizer_path.is_file():
            raise B0EmotionTokenizerError("tokenizer.json 不存在")
        try:
            self._tokenizer = Tokenizer.from_file(str(self.tokenizer_path))
            return self._tokenizer
        except Exception as exc:  # pragma: no cover
            raise B0EmotionTokenizerError(f"tokenizer 加载失败: {exc}") from exc

    @staticmethod
    def _softmax(values: list[float]) -> list[float]:
        peak = max(values)
        exp = [math.exp(item - peak) for item in values]
        total = sum(exp) or 1.0
        return [item / total for item in exp]

    @staticmethod
    def _first_existing(*candidates: Path) -> Path | None:
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None
