"""摘要：W3-P2 跨轮复读门的纯检测器与独立轨迹 DTO。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CROSS_TURN_REPETITION_NGRAM_SIZE = 4
CROSS_TURN_REPETITION_RUNTIME_THRESHOLD = 0.09
CROSS_TURN_REPETITION_RUNTIME_COMPARISON: CrossTurnRepetitionComparison = "gt"
CROSS_TURN_REPETITION_RETRY_INSTRUCTION = (
    "【跨轮复读重试提醒 data-ephemeral】\n"
    "不要复用上一轮回复的原句或提问结构；保留事实含义，用新的表达直接回应当前问题。"
)
CONFIRMATION_INTENT_MAX_CHARS = 32

_CONFIRMATION_RESTATEMENT_TERMS: tuple[str, ...] = (
    "你是说",
    "你的意思是",
    "再说一遍",
    "重复一遍",
    "再讲一遍",
    "帮我确认",
    "再确认",
    "确认一下",
    "没听清",
    "没听懂",
    "我没听清",
    "我没听懂",
    "再说一次",
    "你还记得",
)
_CONFIRMATION_ACK_TERMS: tuple[str, ...] = (
    "确认",
    "好的",
    "好呀",
    "行吧",
    "可以",
    "没问题",
    "同意",
    "赞同",
    "就这样",
    "就这么办",
    "就按这个",
    "按这个来",
    "照这个",
    "按你说的",
    "照办",
    "执行吧",
    "开始吧",
    "去做吧",
    "去吧",
    "做吧",
    "收到",
    "明白了",
    "了解了",
    "知道了",
    "我明白",
    "嗯嗯",
    "ok",
)
_CONFIRMATION_NEGATION_TERMS: tuple[str, ...] = (
    "不用",
    "不要",
    "不行",
    "不可以",
    "不同意",
    "先不",
    "暂不",
    "暂时不",
    "别",
    "反对",
    "不确认",
    "不用确认",
    "别确认",
    "不用重复",
    "别重复",
    "不确定",
    "不太",
    "不对",
    "不是吧",
    "不是的",
    "没想好",
    "重新",
    "换一个",
    "换个",
)
_CONFIRMATION_QUESTION_TERMS: tuple[str, ...] = (
    "？",
    "?",
    "吗",
    "呢",
    "怎么",
    "为什么",
    "啥",
    "多久",
    "多少",
    "什么",
)
_CONFIRMATION_WITHDRAWAL_TERMS: tuple[str, ...] = (
    "再想想",
    "再考虑",
    "等等",
    "慢着",
    "等一下",
    "先等等",
    "算了",
    "停一下",
    "不急",
)
_CONFIRMATION_APPEND_TERMS: tuple[str, ...] = (
    "还有",
    "另外",
    "顺便",
    "对了",
    "补充",
    "加一个",
    "再加",
)

CrossTurnRepetitionAction = Literal["bypass", "direct", "retry"]
CrossTurnRepetitionComparison = Literal["gt", "gte"]
CrossTurnRepetitionOutcome = Literal["bypass", "direct", "retry", "fallback"]


@dataclass(frozen=True)
class CrossTurnRepetitionDecision:
    """摘要：记录一次跨轮 4-gram 判定的输入资格、得分与动作。

    参数：
        action: 本次判定的确定性动作。
        score: 4-gram Jaccard 得分；未进入判定时为 ``None``。
        threshold: 本次使用的阈值；未进入判定时为 ``None``。
        comparison: 阈值比较符号。
        previous_ngrams: 上一轮回复的去重 4-gram 数量。
        current_ngrams: 当前候选回复的去重 4-gram 数量。
        reason: 稳定的判定原因码。
        confirmation_intent: 是否因用户确认或重申意图豁免判定。
    """

    action: CrossTurnRepetitionAction
    score: float | None = None
    threshold: float | None = None
    comparison: CrossTurnRepetitionComparison = "gt"
    previous_ngrams: int = 0
    current_ngrams: int = 0
    reason: str = "missing_previous_or_current_reply"
    confirmation_intent: bool = False


@dataclass(frozen=True)
class CrossTurnRepetitionTrace:
    """摘要：预留独立于 PersonaL4Trace 的首扫、重试与终态轨迹。

    参数：
        enabled: 本轮是否启用复读门。
        first: 首次候选判定。
        retry: 单次重试候选判定。
        retry_taken: 是否消费共享的人格出口重试槽位。
        outcome: 复读门最终结果。
    """

    enabled: bool = False
    first: CrossTurnRepetitionDecision | None = None
    retry: CrossTurnRepetitionDecision | None = None
    retry_taken: bool = False
    outcome: CrossTurnRepetitionOutcome = "bypass"


def compact_for_cross_turn_repetition(text: str) -> str:
    """摘要：移除全部空白，保持与 W2 归档指标一致的字符口径。

    参数：
        text: 待归一化文本。

    返回值：
        移除空白后的文本。
    """

    return "".join(str(text or "").split())


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def detect_confirmation_intent(user_message: str | None) -> bool:
    """摘要：确定性高精度判定用户确认、重申或引用请求意图。

    参数：
        user_message: 触发当前候选回复的用户输入；缺失时为 ``None``。

    返回值：
        是否豁免本轮跨轮复读判定。
    """

    compact = compact_for_cross_turn_repetition(user_message or "")
    if not compact or len(compact) > CONFIRMATION_INTENT_MAX_CHARS:
        return False
    lowered = compact.lower()
    vetoed = (
        _contains_any(lowered, _CONFIRMATION_NEGATION_TERMS)
        or _contains_any(lowered, _CONFIRMATION_WITHDRAWAL_TERMS)
        or _contains_any(lowered, _CONFIRMATION_APPEND_TERMS)
    )
    if vetoed:
        return False
    if _contains_any(lowered, _CONFIRMATION_RESTATEMENT_TERMS):
        return True
    return _contains_any(lowered, _CONFIRMATION_ACK_TERMS) and not _contains_any(
        lowered,
        _CONFIRMATION_QUESTION_TERMS,
    )


def cross_turn_char_ngrams(
    text: str,
    *,
    size: int = CROSS_TURN_REPETITION_NGRAM_SIZE,
) -> frozenset[str]:
    """摘要：生成去重字符 n-gram，并复现 W2 指标的短文本口径。

    参数：
        text: 输入文本。
        size: n-gram 元数，必须为正整数。

    返回值：
        去重后的字符 n-gram 集合。

    Raises:
        ValueError: ``size`` 不是正整数。
    """

    if size <= 0:
        raise ValueError("ngram_size_must_be_positive")
    compact = compact_for_cross_turn_repetition(text)
    if len(compact) < size:
        return frozenset({compact}) if compact else frozenset()
    return frozenset(compact[index : index + size] for index in range(len(compact) - size + 1))


def cross_turn_repetition_score(
    previous_reply: str,
    current_reply: str,
    *,
    size: int = CROSS_TURN_REPETITION_NGRAM_SIZE,
) -> float:
    """摘要：计算相邻两轮助手回复的字符 n-gram Jaccard 得分。

    参数：
        previous_reply: 上一轮助手回复。
        current_reply: 当前候选回复。
        size: n-gram 元数。

    返回值：
        ``0.0`` 到 ``1.0`` 的 Jaccard 得分。
    """

    previous = cross_turn_char_ngrams(previous_reply, size=size)
    current = cross_turn_char_ngrams(current_reply, size=size)
    if not previous and not current:
        return 0.0
    return len(previous & current) / len(previous | current)


def decide_cross_turn_repetition(
    previous_reply: str,
    current_reply: str,
    *,
    threshold: float,
    comparison: CrossTurnRepetitionComparison,
    user_message: str | None = None,
    size: int = CROSS_TURN_REPETITION_NGRAM_SIZE,
) -> CrossTurnRepetitionDecision:
    """摘要：按冻结比较符号对相邻回复执行纯 4-gram 判定。

    参数：
        previous_reply: 上一轮助手回复。
        current_reply: 当前候选回复。
        threshold: ``0.0`` 到 ``1.0`` 的运行阈值候选。
        comparison: ``gt`` 表示严格大于，``gte`` 表示大于等于。
        user_message: 仅用于确认、重申或引用请求的资格豁免，不参与重合分数。
        size: n-gram 元数。

    返回值：
        无副作用的跨轮复读判定。

    Raises:
        ValueError: 阈值越界或比较符号无效。
    """

    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold_must_be_between_zero_and_one")
    if comparison not in {"gt", "gte"}:
        raise ValueError("comparison_must_be_gt_or_gte")
    if not compact_for_cross_turn_repetition(previous_reply) or not compact_for_cross_turn_repetition(
        current_reply
    ):
        return CrossTurnRepetitionDecision(action="bypass", comparison=comparison)
    if detect_confirmation_intent(user_message):
        return CrossTurnRepetitionDecision(
            action="bypass",
            comparison=comparison,
            reason="user_confirmation_exempt",
            confirmation_intent=True,
        )

    previous_ngrams = cross_turn_char_ngrams(previous_reply, size=size)
    current_ngrams = cross_turn_char_ngrams(current_reply, size=size)
    score = cross_turn_repetition_score(previous_reply, current_reply, size=size)
    matched = score > threshold if comparison == "gt" else score >= threshold
    return CrossTurnRepetitionDecision(
        action="retry" if matched else "direct",
        score=score,
        threshold=threshold,
        comparison=comparison,
        previous_ngrams=len(previous_ngrams),
        current_ngrams=len(current_ngrams),
        reason="threshold_matched" if matched else "threshold_not_matched",
    )
