"""V2 第一步：需求拆解

输入一个问题，输出 1~N 个独立的检索需求。

核心难点不是"怎么拆"，是"什么时候不该拆"：
    并列（分别 / 各）  → 可以拆
    对比（有什么不同）  → 不能拆，拆了就丢掉比较语义
"""
import sys
from pathlib import Path

# 本项目根与 experiments 目录都要在 sys.path 里：
# 根目录提供 app / index_builder 等业务模块，本目录提供 v2_planner / v2_retrieve
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

CHAT_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
CHAT_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "").strip()
CHAT_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip()
DISABLE_THINKING = os.getenv("CHAT_DISABLE_THINKING", "").strip().lower() in ("1", "true", "yes")

client = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)

SPLIT_PROMPT = """你是检索需求拆解器。给定用户的一个问题，判断它包含几个独立的信息需求。

拆分规则：
1. 只有「并列关系」才拆——问题里出现「分别」「各」「以及」，且各部分能独立成问、互不依赖。
2. 「对比关系」绝不拆——出现「有什么不同」「区别」「哪个更」「相比」时，必须作为一个整体检索，
   因为拆开后就丢失了「比较」这个语义。
3. 单主体问题不拆，直接返回原问题。

每个需求改写成一句独立的检索语句：保留关键术语，去掉疑问词，不要添加问题里没有的信息。

只输出 JSON，不要任何解释：
{"needs": ["需求1", "需求2"]}

示例1：
问题：球拍和羽毛球分别有哪些规格限制？
输出：{"needs": ["球拍规格限制", "羽毛球规格限制"]}

示例2：
问题：单打和双打的发球区边界有什么不同？
输出：{"needs": ["单打和双打的发球区边界差异"]}

示例3：
问题：反手高远球的击球点在哪里？
输出：{"needs": ["反手高远球的击球点位置"]}
"""


def split_needs(question: str) -> list[str]:
    """把问题拆成独立检索需求；解析失败时退化为单需求，不抛异常"""
    kwargs = dict(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": SPLIT_PROMPT},
            {"role": "user", "content": question},
        ],
        temperature=0,
    )
    if DISABLE_THINKING:
        kwargs["extra_body"] = {"enable_thinking": False}

    resp = client.chat.completions.create(**kwargs)
    raw = (resp.choices[0].message.content or "").strip()

    # 模型有时会套 ```json 代码块
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()

    try:
        needs = json.loads(raw).get("needs") or []
        needs = [str(n).strip() for n in needs if str(n).strip()]
    except Exception:
        needs = []

    # 兜底：拆解失败就当成单需求，行为退化为 v1，不会更差
    return needs or [question]


if __name__ == "__main__":
    CASES = [
        ("反手高远球的击球点应该在身体哪个位置？", 1, "单需求"),
        ("球拍和羽毛球分别有哪些规格限制？", 2, "并列"),
        ("发球、接发球、重发球分别有什么规则？", 3, "并列"),
        ("单打和双打的发球区边界有什么不同？", 1, "对比·陷阱"),
    ]

    ok = 0
    for q, expect, tag in CASES:
        needs = split_needs(q)
        hit = len(needs) == expect
        ok += hit
        print(f"[{'OK ' if hit else 'FAIL'}] {tag:<10} 期望 {expect} 实得 {len(needs)}")
        print(f"       问题：{q}")
        for i, n in enumerate(needs, 1):
            print(f"       需求{i}：{n}")
        print()

    print(f"通过 {ok}/{len(CASES)}")
