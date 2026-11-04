"""Agent 核心：决策循环 + 证据合并

与旧版的区别（旧版是「一次性路由」，不是 Agent）：

    旧：route() 一次决定 → 无条件执行完 → 各自生成再拼接
        问题① 执行中看不到结果，不能补查
        问题② 多工具结果分别生成，同一份回答会自相矛盾

    新：循环决策 → 每轮看到已有观察 → 够了才停 → 一次性生成
        模型在每一步都能改变主意

关键设计：
    1. 观察结果累积，不覆盖——第二轮能看到第一轮查到了什么
    2. 只生成一次，所有证据合并进同一个 prompt
    3. 轮次上限 + 重复调用检测，防止死循环
    4. 单步失败不中断，把失败也作为观察交给模型
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

from agent_tools import generate_with_prompt, query_racket, search_docs

CHAT_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
CHAT_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "").strip()
CHAT_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip()
DISABLE_THINKING = os.getenv("CHAT_DISABLE_THINKING", "").strip().lower() in ("1", "true", "yes")

client = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)

MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "3"))

DECIDE_PROMPT = """你是工具调用 Agent。根据用户问题和**已获得的观察结果**，决定下一步动作。

可用工具：
1. query_racket(model) —— 查某款羽毛球拍的规格参数。
   适用：问题里出现具体型号，如 88S PRO、100ZZ、战戟8000、雷霆80。
2. search_docs(query) —— 检索羽毛球文档（规则条文、技术动作、裁判执行、赛事规程）。

决策规则：
- 问题含具体型号 → 先 query_racket
- **query_racket 返回未收录 → 改用 search_docs 查同品牌/同系列的一般信息**
- 问题涉及规则/技术/裁判/赛事 → search_docs
- **已有观察足以回答 → 输出 answer，不要多查**
- 已有观察不足但轮次将尽 → 也要输出 answer，并在回答里说明缺什么
- 不要重复完全相同的调用

只输出 JSON，不要解释：
{"action": "query_racket", "args": {"model": "88S PRO"}, "reason": "问题含具体型号"}
{"action": "search_docs", "args": {"query": "拍面尺寸规定"}, "reason": "问规则条文"}
{"action": "answer", "reason": "证据已覆盖问题"}"""

ANSWER_PROMPT = """你在回答羽毛球问题。下面是工具查到的**全部证据**，请综合它们给出一个连贯的回答。

要求：
1. 参数值、条款号、页码必须**原样引用**，不得改写或推测
2. **综合所有证据**，不要分段各说各的——如果装备和规则都相关，要在同一段话里讲清楚
3. 证据之间如有冲突，明确指出冲突在哪
4. 证据不足时说明缺什么，不要编
5. 中文回答，控制在 200 字以内"""


def _chat(messages) -> str:
    kwargs = dict(model=CHAT_MODEL, messages=messages, temperature=0)
    if DISABLE_THINKING:
        kwargs["extra_body"] = {"enable_thinking": False}
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def decide(question: str, observations: list[dict], step: int) -> dict:
    """看已有观察，决定下一步动作"""
    if observations:
        seen = "\n\n".join(
            f"[第 {i} 步] {o['action']}({json.dumps(o['args'], ensure_ascii=False)})\n"
            f"结果：{o['summary']}"
            for i, o in enumerate(observations, 1)
        )
    else:
        seen = "（尚无任何工具调用）"

    user = (f"用户问题：{question}\n\n已获得的观察：\n{seen}\n\n"
            f"当前第 {step} 轮，最多 {MAX_STEPS} 轮。决定下一步动作。")

    try:
        raw = _chat([{"role": "system", "content": DECIDE_PROMPT},
                     {"role": "user", "content": user}])
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.M).strip()
        d = json.loads(raw)
        if d.get("action") not in ("query_racket", "search_docs", "answer"):
            raise ValueError("unknown action")
        return d
    except Exception:
        return ({"action": "answer", "reason": "决策解析失败"}
                if observations
                else {"action": "search_docs", "args": {"query": question}, "reason": "兜底"})


def act(decision: dict) -> dict:
    """执行一个动作，返回观察记录（失败也记录，不抛异常）"""
    action, args = decision["action"], decision.get("args") or {}

    if action == "query_racket":
        model = args.get("model") or ""
        result = query_racket(model)
        summary = (f"命中 {result['model']}，建议磅数 {result['tension_raw']}，"
                   f"手感 {result['stiffness']}" if result.get("found")
                   else f"未收录型号「{model}」")
        return {"action": action, "args": args, "result": result, "summary": summary}

    hits = search_docs(args.get("query") or "")
    srcs = sorted({f"{c['source'][:14]}p{c['page']}" for _, c in hits})
    return {"action": action, "args": args, "result": hits,
            "summary": f"命中 {len(hits)} 块，来源 {srcs[:3]}"}


def format_evidence(observations: list[dict]) -> str:
    """把所有工具结果合并成一份证据文本"""
    blocks = []
    for o in observations:
        if o["action"] == "query_racket":
            r = o["result"]
            if not r.get("found"):
                blocks.append(f"[装备库] 未收录型号「{r['query']}」")
                continue
            lines = [f"[装备库] {r['brand']} {r['model']}"]
            for label, key in [("规格", "weights"), ("建议磅数", "tension_raw"),
                               ("击球手感", "stiffness"), ("平衡点", "balance_point"),
                               ("长度", "length"), ("拍框", "frame_material"),
                               ("拍杆", "shaft_material")]:
                v = (r.get(key) or "").strip()
                if v:
                    lines.append(f"{label}：{v}")
            blocks.append("\n".join(lines))
        elif o["action"] == "search_docs":
            for score, c in o["result"]:
                blocks.append(f"[{c.get('doc_type', '?')}] {c['source']} 第 {c['page']} 页\n{c['text']}")
    return "\n\n".join(blocks)


def gather(question: str, max_steps: int = MAX_STEPS) -> tuple[list[dict], str]:
    """跑决策循环，返回 (步骤记录, 合并后的证据文本)"""
    observations: list[dict] = []
    called: set = set()

    for step in range(1, max_steps + 1):
        decision = decide(question, observations, step)

        if decision["action"] == "answer":
            observations.append({"action": "answer", "args": {}, "result": None,
                                 "summary": decision.get("reason", "")})
            break

        key = (decision["action"], json.dumps(decision.get("args") or {}, sort_keys=True))
        if key in called:
            observations.append({"action": "answer", "args": {}, "result": None,
                                 "summary": "检测到重复调用，提前结束"})
            break
        called.add(key)

        observations.append(act(decision))

    return observations, format_evidence(observations)


def stream_answer(question: str, evidence: str, usage: dict | None = None):
    """基于合并后的证据流式生成最终回答"""
    yield from generate_with_prompt(question, evidence, ANSWER_PROMPT, usage)


def run(question: str, max_steps: int = MAX_STEPS) -> tuple[list[dict], str]:
    """非流式：返回 (步骤, 完整回答)"""
    steps, evidence = gather(question, max_steps)
    if not evidence:
        return steps, "没有找到相关信息。"
    return steps, "".join(stream_answer(question, evidence, {}))


if __name__ == "__main__":
    CASES = [
        "ASTROX 88S PRO 的 4U 建议磅数是多少？",
        "雷霆99 的建议磅数是多少？",
        "88S PRO 适合进攻吗，规则里对拍面尺寸有要求吗？",
        "60 秒的间歇出现在什么时候？",
    ]
    for q in CASES:
        steps, ans = run(q)
        print("=" * 74)
        print(f"问：{q}")
        for i, s in enumerate(steps, 1):
            print(f"  {i}. {s['action']:<13} {json.dumps(s['args'], ensure_ascii=False):<38}"
                  f" → {s['summary'][:46]}")
        print(f"答：{ans[:260]}".replace("\n", " "))
        print()
