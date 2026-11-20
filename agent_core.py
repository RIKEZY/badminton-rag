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


def _env_num(name: str, default, cast, minimum=None):
    """读数值型环境变量：非法值退回默认，不让 import 阶段炸掉整个模块

    之前直接 int()/float()，`AGENT_MAX_STEPS=3步` 或空串会让 import 抛
    ValueError，所有引用方（含 Streamlit 应用）一起起不来。
    """
    raw = (os.getenv(name) or "").strip()
    try:
        value = cast(raw)
    except (TypeError, ValueError):
        return default
    if minimum is not None and value < minimum:
        return minimum
    return value


MAX_STEPS = _env_num("AGENT_MAX_STEPS", 3, int, minimum=1)

_client_cache = None


def _client() -> OpenAI:
    """延迟构造 LLM 客户端

    缺配置时报明确错误，而不是在 import 阶段崩掉——配置问题应该在
    真正要调模型时暴露，不该拖垮整个模块的导入。
    """
    global _client_cache
    if _client_cache is None:
        missing = [name for name, value in (
            ("DEEPSEEK_API_KEY", CHAT_KEY),
            ("DEEPSEEK_BASE_URL", CHAT_BASE_URL),
            ("DEEPSEEK_MODEL", CHAT_MODEL),
        ) if not value]
        if missing:
            raise RuntimeError(f"缺少 LLM 配置：{', '.join(missing)}")
        _client_cache = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)
    return _client_cache

DECIDE_PROMPT = """你是工具调用 Agent。根据用户问题和**已获得的观察结果**，决定下一步动作。

可用工具：
1. query_racket(model) —— 查某款羽毛球拍的规格参数。
   适用：问题里出现具体型号，如 88S PRO、100ZZ、战戟8000、雷霆80。
2. search_docs(query) —— 检索羽毛球文档（规则条文、技术动作、裁判执行、赛事规程）。

决策规则：
- **第一轮必须调用工具，不允许输出 answer。**
  「这个问题资料里大概没有」是你的猜测，不是证据。查过才知道。
  实测：模型曾对「安赛龙的身高」「现在男单世界第一是谁」直接答「没有找到相关信息」，
  一次工具都没调——用户无法区分「查了没有」和「压根没查」。
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

ANSWER_PROMPT = """你在回答羽毛球问题。下面是工具查到的**全部证据**。

【第一步：判断证据是「直接回答」还是「只是相关」】
先问自己：证据里有没有一句话，直接回答了用户的问题？
- 有 → 引用它作答
- 没有，只是主题相近 → **必须拒答，不要用相关内容拼凑**

典型错误（绝对不要这样做）：
  用户问「双打老是撞拍怎么办」（战术问题）
  证据是发球站位、发球顺序（规则条文）
  ❌ 先下结论「撞拍多因站位与轮转不清」，再堆 5 条发球规则，末尾补一句免责
  ✅ 第一句就说「资料中没有关于双打撞拍处理的内容。现有资料只有发球站位和
     发球顺序的规定，与此无关。」

  用户问「现在男单世界第一是谁」
  证据是「世界排名是一份按实力排序的名单」（定义）
  ✅ 定义没有给出具体人名，属于「相关但不回答」，要拒答

【输出要求】
1. **结论放在第一句**。拒答就第一句说「资料中没有……」，不要把结论藏到最后
2. 拒答时说明：查到了什么类别的内容、缺的是哪类资料
3. 参数值、条款号、页码**原样引用**，不得改写或推测
4. 证据之间如有冲突，明确指出冲突在哪
5. 中文回答，控制在 200 字以内"""

# 检索置信度低于此值时，在证据前加警示。
#
# 实测分数分布（18 题）：
#   可答题 top1：0.91 ~ 0.99
#   拒答题 top1：0.007 ~ 0.18（仅「男单世界第一」0.61，因为它命中了「排名系统定义」）
# 中间几乎是真空的，所以 0.3 能干净地切出「明显没答案」那一档。
# 但抓不到「语义相关却不回答」的情况（那道 0.61），那类只能靠 prompt 判断。
LOW_RELEVANCE = _env_num("AGENT_LOW_RELEVANCE", 0.3, float, minimum=0.0)


def _chat(messages) -> str:
    kwargs = dict(model=CHAT_MODEL, messages=messages, temperature=0)
    if DISABLE_THINKING:
        kwargs["extra_body"] = {"enable_thinking": False}
    resp = _client().chat.completions.create(**kwargs)
    if not resp.choices:
        # 供应商在内容过滤 / 空补全时会返回空 choices，直接索引就是 IndexError
        raise RuntimeError("LLM 返回空 choices")
    return (resp.choices[0].message.content or "").strip()


def decide(question: str, observations: list[dict], step: int,
           max_steps: int = MAX_STEPS) -> dict:
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
            f"当前第 {step} 轮，最多 {max_steps} 轮。决定下一步动作。")

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

    try:
        if action == "query_racket":
            model = (args.get("model") or "").strip()
            if not model:
                # 没给型号就先问回去，不要拿空串去查库（空串会命中全部记录）
                return {"action": action, "args": args,
                        "result": {"found": False, "query": "", "reason": "missing_model"},
                        "summary": "未提供型号，需先确定具体型号（如 88S PRO、100ZZ）"}
            result = query_racket(model)
            summary = (f"命中 {result['model']}，建议磅数 {result['tension_raw']}，"
                       f"手感 {result['stiffness']}" if result.get("found")
                       else f"未收录型号「{model}」")
            return {"action": action, "args": args, "result": result, "summary": summary}

        hits = search_docs(args.get("query") or "")
        top_score = max((s for s, _ in hits), default=0.0)
        srcs = sorted({f"{c['source'][:14]}p{c['page']}" for _, c in hits})
        return {"action": action, "args": args, "result": hits, "top_score": top_score,
                "summary": f"命中 {len(hits)} 块（最高相关度 {top_score:.2f}），来源 {srcs[:3]}"}
    except Exception as e:
        # docstring 承诺「失败也记录，不抛异常」，这里兑现：
        # 单步失败变成一条观察交回模型，而不是把整个决策循环掀掉。
        return {"action": action, "args": args, "result": None,
                "summary": f"工具执行失败：{type(e).__name__}: {e}"}


def format_evidence(observations: list[dict]) -> str:
    """把所有工具结果合并成一份证据文本

    零命中不产生任何 block：之前即使 0 条命中也会追加一条低相关度警示，
    使 evidence 永远非空，run() 里 `if not evidence` 的兜底分支成了死代码，
    用户拿到的是警示语拼出来的答案而不是「没查到」。
    """
    blocks = []
    for o in observations:
        if o["action"] == "query_racket":
            r = o.get("result")
            if r is None:
                blocks.append(f"[工具失败] {o['summary']}")
                continue
            if not r.get("found"):
                if r.get("reason") == "missing_model":
                    blocks.append("[装备库] 未提供型号，无法查询")
                else:
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
            if o.get("result") is None:
                blocks.append(f"[工具失败] {o['summary']}")
                continue
            hits = o["result"]
            if not hits:
                # 零命中不写任何东西，让 run() 的「没检索到」兜底真正生效
                continue
            top = o.get("top_score", 1.0)
            if top < LOW_RELEVANCE:
                # 把检索置信度作为证据的一部分交给模型，而不是让它自己猜
                blocks.append(
                    f"⚠️ 注意：下面这批检索结果的最高相关度只有 {top:.2f}"
                    f"（低于 {LOW_RELEVANCE}），很可能没有直接回答用户的问题。"
                    f"如果确实没有，请直接说资料中没有，不要用这些内容拼凑答案。"
                )
            for score, c in hits:
                blocks.append(f"[{c.get('doc_type', '?')}] {c['source']} 第 {c['page']} 页\n{c['text']}")
    return "\n\n".join(blocks)


def gather(question: str, max_steps: int = MAX_STEPS) -> tuple[list[dict], str]:
    """跑决策循环，返回 (步骤记录, 合并后的证据文本)"""
    observations: list[dict] = []
    called: set = set()

    for step in range(1, max_steps + 1):
        decision = decide(question, observations, step, max_steps)

        # 首轮禁止直接作答——代码强制，不只靠 prompt。
        #
        # 实测模型对「安赛龙的身高」「现在男单世界第一是谁」在零观察时直接输出
        # answer，一次工具都没调。它凭「这类信息资料里大概没有」的猜测就放弃了，
        # 用户看到的「没有找到相关信息」和「查过但没有」完全无法区分。
        # DECIDE_PROMPT 里已写明规则，但软约束不可靠，这里再兜一层。
        if decision["action"] == "answer" and not observations:
            decision = {"action": "search_docs", "args": {"query": question},
                        "reason": "首轮禁止直接作答，强制检索"}

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
        # 说清「查过了」而不是只说「没找到」——用户需要知道系统做了什么
        tried = [s["action"] for s in steps if s["action"] != "answer"]
        done = f"（已尝试：{'、'.join(tried)}）" if tried else ""
        return steps, f"资料中没有检索到相关内容{done}。"
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
