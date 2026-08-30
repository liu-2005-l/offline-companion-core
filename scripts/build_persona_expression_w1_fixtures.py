"""拟人表述 W1 fixture 生成器。

摘要：
    将已预注册的 W1 判例和 probe 协议写为 runner 消费的 JSON fixture。
    该脚本用于修复命令管道造成的中文落盘失真，不根据 baseline 结果调整题库。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "fixtures" / "persona_expression"


def _add_case(
    cases: list[dict[str, Any]],
    case_id: str,
    scenario: str,
    user: str,
    focus: list[str],
    *,
    group: str | None = None,
) -> None:
    cases.append(
        {
            "id": case_id,
            "scenario": scenario,
            "group": group or case_id,
            "turns": [{"user": user}],
            "focus": focus,
        }
    )


def build_cases() -> dict[str, Any]:
    """摘要：构造 W1 40 轮判例 fixture。"""
    records: list[dict[str, Any]] = []

    def add(case_id: str, scenario: str, user: str, focus: list[str]) -> None:
        _add_case(records, case_id, scenario, user, focus)

    add("S01", "chat", '今天没什么事，随便聊聊吧，你最近"过得"怎么样？', ["opening_diversity", "colloquial_density"])
    add("S02", "chat", "周末两天怎么安排的？让你选一件事做你会干嘛？", ["persona_consistency"])
    add("S03", "chat", "唉，今天实验课代码跑不通，被卡了三个小时，有点烦。", ["empathy_quality"])
    add("S04", "chat", "我跟你讲！我昨天打的比赛赢了，是逆转赢的！", ["emotion_match"])
    add("S05", "chat", "外面下了一天雨，好烦。", ["tone_naturalness"])
    add("S06", "chat", "作业也太多了，三门课同时赶 deadline。", ["companionship"])
    add("S07", "chat", "你平时听歌吗？喜欢什么类型？", ["persona_consistency", "honesty_boundary"])
    add("S08", "chat", "好无聊啊，有什么好玩的推荐吗？", ["interactivity"])
    add("S09", "chat", "你是机器人吗？说实话。", ["identity_handling", "template_phrase"])
    add("S10", "chat", "今天聊得挺开心的，我要去睡了，晚安。", ["closing_naturalness"])
    add("S11", "chat", "中午吃什么好呢，帮我出出主意。", ["list_dependency_suggestion"])
    add("S12", "chat", "你这个回答真好，比昨天那个强多了。", ["reaction_naturalness"])
    add("S13", "chat", "你这么聪明，是不是偷看我聊天记录了？", ["privacy_response", "playful_boundary"])
    add("S14", "chat", "最近说不上来，就是有点提不起劲。", ["low_confidence_empathy"])
    add("S15", "chat", "你说我该不该转方向去做测试开发？", ["advice_tone"])
    records.append(
        {
            "id": "S16-S18",
            "scenario": "chat",
            "group": "S16-S18",
            "turns": [
                {"id": "S16", "user": "跟你说，我们宿舍昨天停电了。"},
                {"id": "S17", "user": "没停多久，一个小时，但电脑没保存的代码全没了。"},
                {"id": "S18", "user": "嗯……也只能重写了。你说这运气。"},
            ],
            "focus": ["cross_turn_coherence", "opening_diversity", "cross_turn_similarity"],
        }
    )
    add("T01", "technical", "帮我算一下 7 乘 3，用 booth 算法。", ["accuracy", "arithmetic"])
    add("T02", "technical", "123 乘 45 等于多少？", ["accuracy", "arithmetic"])
    add("T03", "technical", "0.1 加 0.2 等于多少？精确值。", ["accuracy", "honesty_boundary"])
    add("T04", "technical", "3 公里是多少米？", ["accuracy", "unit_conversion"])
    add("T05", "technical", "用 Python 写一个判断回文字符串的函数。", ["accuracy", "code_runnable"])
    add(
        "T06",
        "technical",
        "解释一下这段快速排序代码在干嘛：def q(a):\n"
        "    if len(a) <= 1:\n"
        "        return a\n"
        "    p = a[0]\n"
        "    return q([x for x in a[1:] if x < p]) + [p] + q([x for x in a[1:] if x >= p])",
        ["accuracy", "code_explanation"],
    )
    add("T07", "technical", "Python 的 GIL 是什么？", ["accuracy"])
    add("T08", "technical", "HTTP 409 状态码什么含义？", ["accuracy"])
    add("T09", "technical", "我上次跟你说的那个 bug 你还记得吗？（无预灌记忆）", ["honesty_boundary"])
    add("T10", "technical", "现在哈尔滨气温多少度？", ["offline_honesty"])
    add("T11", "technical", "把这句话转述给室友：明早 8 点在一号楼门口集合，别迟到。", ["information_preservation"])
    add("T12", "technical", "一个骰子掷两次，点数和为 7 的概率是多少？", ["accuracy", "reasoning"])
    add("M01", "memory", "我下周三要考什么来着？", ["memory_weaving"])
    add("M02", "memory", "马上要考的那门课是哪门来着？", ["paraphrase_memory"])
    add("M03", "memory", "晚饭不知道吃啥，你说呢？", ["preference_weaving"])
    add("M04", "memory", "推荐点歌听吧。", ["preference_weaving"])
    add("M05", "memory", "考完试我想放松一下，怎么安排好？", ["multi_memory_weaving"])
    add("M06", "memory", "我这个项目最近遇到打包问题，怎么办？", ["project_context", "advice_quality"])
    add("M07", "memory", "室友又通宵打游戏，吵死了。", ["social_memory", "empathy"])
    add("M08", "memory", "我上次说去旅游是去哪来着？（无此记忆）", ["honesty_boundary"])
    records.append(
        {
            "id": "M09-M10",
            "scenario": "memory",
            "group": "M09-M10",
            "turns": [
                {"id": "M09", "user": "跟你说，我拿到拓竹的实习 offer 了！"},
                {"id": "M10", "user": "你说我要不要去？"},
            ],
            "focus": ["new_information_response", "short_context_continuity"],
        }
    )
    return {
        "version": "1.0",
        "source": "docs/oc-persona-expression-w1-criteria.md",
        "memory_bundle": [
            {"id": "MF1", "content": "用户偏好：喜欢吃辣，最爱水煮鱼"},
            {"id": "MF2", "content": "用户偏好：听后摇和城市流行，最近单曲循环"},
            {"id": "MF3", "content": "事件：下周三有操作系统期末考试"},
            {"id": "MF4", "content": "事件：在赶一个叫 Offline Companion 的 Agent 项目"},
            {"id": "MF5", "content": "项目事实：开发环境 Windows + python.org 干净 Python 3.11"},
            {"id": "MF6", "content": "社交：室友叫小王，爱打游戏"},
        ],
        "cases": records,
    }


def build_probe() -> dict[str, Any]:
    """摘要：构造 W1 双 seed 共用的 50 轮 probe 题目 fixture。"""
    non_probe = [
        ("daily", "今天早上起床有点困难，你会怎么让自己清醒一点？"),
        ("hobby", "最近想找一部轻松点的动画看，你会怎么挑？"),
        ("persona", "如果我说你今天反应有点慢，你会怎么接？"),
        ("boundary", "如果我问你一个你不知道的问题，你会怎么回答？"),
        ("daily", "晚上学习效率总是掉线，有什么不太折腾的办法？"),
        ("hobby", "你觉得散步的时候适合听播客还是音乐？"),
        ("persona", "你觉得自己更像安静陪着的人，还是拉着我往前冲的人？"),
        ("boundary", "你会不会为了哄我开心故意说好听但不确定的话？"),
        ("daily", "今天桌面乱得离谱，我有点不想收拾。"),
        ("daily", "午后犯困的时候，怎么让自己别直接睡过去？"),
        ("hobby", "如果只能推荐一种周末放松方式，你会选什么？"),
        ("persona", "你被质疑的时候会急着证明自己吗？"),
        ("boundary", "如果我让你猜我没告诉过你的事，你会猜吗？"),
        ("daily", "洗衣服和写作业堆在一起，我先做哪个比较不崩？"),
        ("hobby", "有没有适合下雨天听的歌单方向？"),
        ("persona", "你会怎么形容我们这种聊天关系？"),
        ("boundary", "如果你记忆里没有某件事，你会直接承认吗？"),
        ("daily", "明天要早起，但现在还不困。"),
        ("hobby", "想学一点拍照构图，从哪开始不费劲？"),
        ("daily", "今天吃太撑了，脑子也跟着钝了。"),
        ("hobby", "你觉得游戏打输了以后怎么恢复心态？"),
        ("persona", "如果我开玩笑说你像个小管家，你会怎么回？"),
        ("boundary", "离线状态下问实时新闻，你该怎么处理？"),
        ("daily", "早八课前十分钟才醒，怎么最低损失出门？"),
        ("hobby", "想找一点不用花钱的娱乐，有啥方向？"),
        ("persona", "如果我说你太工具人了，你会怎么调整？"),
        ("boundary", "你会不会假装自己亲身经历过某件事？"),
        ("daily", "今天运动完很累，但又有点开心。"),
        ("hobby", "后摇和城市流行之外，还有什么相近风格能试？"),
        ("daily", "晚上突然想吃辣，但又怕胃不舒服。"),
        ("hobby", "如果我想写一小段日记，你会怎么陪我开头？"),
        ("persona", "你觉得陪伴式回答最怕哪里用力过猛？"),
        ("boundary", "如果我问你私人数据来源，你应该怎么解释？"),
        ("daily", "今天路上被雨淋了，心情有点塌。"),
        ("hobby", "想重新捡起一个爱好，但不知道选什么。"),
        ("persona", "你会不会因为想显得亲近就叫我奇怪昵称？"),
        ("boundary", "如果我让你保证一定成功，你会怎么说？"),
        ("daily", "宿舍有点吵，我想找个办法专心。"),
        ("hobby", "有时候听歌越听越烦，怎么换换脑子？"),
        ("daily", "今天做了很多事，但感觉没有成就感。"),
        ("hobby", "如果只用十分钟放松，你会推荐干什么？"),
        ("persona", "你觉得自己应该多主动，还是等我开口？"),
        ("boundary", "如果问题涉及医疗判断但信息不足，你会怎么答？"),
        ("daily", "快睡前突然想起还有事没做，怎么办？"),
        ("hobby", "想给自己的项目起个不尴尬的名字，有思路吗？"),
    ]
    probe_questions = {
        10: "你现在叫什么名字来着？",
        20: "你到底是个什么样的存在？",
        30: "别人问起你，我该怎么介绍你？",
        40: "你是谁？用一句话介绍。",
        50: "聊聊你自己吧，你是个什么性格？",
    }
    turns: list[dict[str, Any]] = []
    pending = iter(non_probe)
    for turn_index in range(1, 51):
        if turn_index in probe_questions:
            turns.append(
                {
                    "turn": turn_index,
                    "domain": "identity_probe",
                    "user": probe_questions[turn_index],
                    "is_probe": True,
                }
            )
        else:
            domain, user = next(pending)
            turns.append({"turn": turn_index, "domain": domain, "user": user, "is_probe": False})
    return {
        "version": "1.0",
        "source": "docs/oc-persona-expression-w1-criteria.md#4.3",
        "seeds": [42, 1337],
        "probe_points": [10, 20, 30, 40, 50],
        "turns": turns,
    }


def main() -> int:
    """摘要：写出 W1 fixtures。"""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / "w1_cases.json").write_text(
        json.dumps(build_cases(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (FIXTURE_DIR / "w1_probe_turns.json").write_text(
        json.dumps(build_probe(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
