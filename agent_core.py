"""Agent 核心：路由 + 执行

最小可用的 Agent 骨架，只做一件事：判断该调哪个工具，然后执行。

三条设计原则：
    1. 路由失败必须降级到 search_docs，不能崩（v1 行为兜底）
    2. 装备参数不过模型生成，模板直出（杜绝幻觉）
    3. 多个工具的结果按顺序拼接，不互相污染
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

from agent_tools import (describe_racket, format_racket_evidence, generate_answer,
                         generate_equipment_answer, generate_stream_answer,
                         query_racket, search_docs)

CHAT_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
CHAT_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "").strip()
CHAT_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip()
DISABLE_THINKING = os.getenv("CHAT_DISABLE_THINKING", "").strip().lower() in ("1", "true", "yes")

client = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)

ROUTER_PROMPT = """你是工具路由器。根据用户问题，决定调用哪些工具。

可用工具：
1. query_racket(model) —— 查某款羽毛球拍的规格参数。
   适用：问题里出现**具体型号**，如 88S PRO、100ZZ、11 PRO、战戟8000、雷霆80、风刃900。
   model 参数填用户提到的型号原文，不要改写。

2. search_docs(query) —— 检索羽毛球知识文档（规则条文、技术动作、通用装备知识）。
   适用：**泛化问题**，没有具体型号。如「反手高远球怎么打」「发球规则是什么」
   「什么拍适合进攻」「球拍磅数一般多少」。

判断规则：
- 出现具体型号 → query_racket
- 问多个型号（对比、哪个高）→ 每个型号各调一次 query_racket
- 泛化问题 → search_docs
- 既有具体型号又有泛化问题 → 两个工具都调

只输出 JSON，不要解释：
{"calls": [{"tool": "query_racket", "args": {"model": "88S PRO"}}]}"""


def route(question: str) -> list[dict]:
    """判断该调哪些工具；解析失败时降级为文档检索"""
    kwargs = dict(
        model=CHAT_MODEL,
        messages=[{"role": "system", "content": ROUTER_PROMPT},
                  {"role": "user", "content": question}],
        temperature=0,
    )
    if DISABLE_THINKING:
        kwargs["extra_body"] = {"enable_thinking": False}

    try:
        resp = client.chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()
        calls = json.loads(raw).get("calls") or []
        calls = [c for c in calls if isinstance(c, dict) and c.get("tool")]
    except Exception:
        calls = []

    if not calls:
        return [{"tool": "search_docs", "args": {"query": question}}]
    return calls


def execute(calls: list[dict]):
    """按路由结果执行工具调用，返回 (装备结果列表, 文档命中列表)"""
    racket_results, doc_hits = [], []
    for c in calls:
        name, args = c["tool"], (c.get("args") or {})
        if name == "query_racket":
            racket_results.append(query_racket(args.get("model") or ""))
        elif name == "search_docs":
            doc_hits.extend(search_docs(args.get("query") or ""))
    return racket_results, doc_hits


def run(question: str) -> str:
    """路由 → 执行 → 拼装答案（非流式）"""
    racket_results, doc_hits = execute(route(question))

    parts = []
    if racket_results:
        # 装备参数先交给模型推理（回答问题），再附上原始明细供核对
        evidence = format_racket_evidence(racket_results)
        parts.append("".join(generate_equipment_answer(question, evidence)))
        parts.append("**参数明细**\n\n" + "\n\n".join(describe_racket(r) for r in racket_results))
    if doc_hits:
        ans, _ = generate_answer(question, doc_hits)
        parts.append(ans)

    return "\n\n---\n\n".join(parts) if parts else "没有找到相关信息。"


def run_stream(question: str, calls: list[dict] | None = None, usage: dict | None = None):
    """流式版本：模型推理答案先流式输出，原始参数明细随后附上"""
    racket_results, doc_hits = execute(calls if calls is not None else route(question))

    if racket_results:
        evidence = format_racket_evidence(racket_results)
        yield from generate_equipment_answer(question, evidence, usage)
        yield "\n\n---\n\n**参数明细**（原始数据，可核对）\n\n"
        yield "\n\n".join(describe_racket(r) for r in racket_results)
        if doc_hits:
            yield "\n\n---\n\n"

    if doc_hits:
        yield from generate_stream_answer(question, doc_hits, usage)


if __name__ == "__main__":
    CASES = [
        ("精确型号", "ASTROX 88S PRO 的 4U 建议磅数是多少？"),
        ("泛化问题", "反手高远球的击球点应该在身体哪个位置？"),
        ("多型号对比", "88S PRO 和 88D TOUR 的建议磅数差多少？"),
        ("型号不存在", "雷霆99 的建议磅数是多少？"),
    ]

    for tag, q in CASES:
        calls = route(q)
        print("=" * 70)
        print(f"[{tag}] {q}")
        print(f"  路由 → {[c['tool'] + '(' + str(c.get('args')) + ')' for c in calls]}")
        print(f"  回答 → {run(q)[:220].replace(chr(10), ' ')}")
        print()
