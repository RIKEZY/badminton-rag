"""Agent 的工具层

两个工具，对应两条数据链路：
    query_racket  → SQLite 精确查询（装备参数）
    search_docs   → 向量检索（规则/技术文档）

设计原则：工具只返回结构化数据，不做自然语言加工。
装备参数尤其不能过 LLM——型号、磅数这类精确值，生成一遍就有幻觉风险。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RAG_TAG", "rules")
os.environ.setdefault("RAG_DATA_DIR", str(ROOT / "data_rules_only"))

from tools.equipment_query import search_model


def query_racket(model: str) -> dict:
    """按型号查装备参数。未命中时 found=False，不编造。"""
    rows = search_model(model)
    if not rows:
        return {"found": False, "query": model}

    r = rows[0]
    return {
        "found": True,
        "query": model,
        "model": r["model"],
        "brand": r["brand"],
        "series": r["series"],
        "weights": r["weights"],
        "tension_raw": r["tension_raw"],
        "stiffness": r["stiffness"],
        "balance_point": r["balance_point"],
        "length": r["length"],
        "frame_material": r["frame_material"],
        "shaft_material": r["shaft_material"],
        "source": r["source"],
    }


def _runtime():
    """获取正在运行的 app 模块

    **不能直接 `import app`**：Streamlit 把 app.py 当 `__main__` 执行，
    此时 `sys.modules` 里没有 `app`，`import app` 会把整个脚本重新执行一遍
    ——包括侧边栏的 st.slider，触发 StreamlitDuplicateElementId。

    所以先看 `__main__` 是否就是正在跑的 app（有 retrieve/chunks 即认定），
    是就直接复用；不是（CLI 场景，如 python agent_core.py）才正常 import。
    """
    main = sys.modules.get("__main__")
    if main is not None and hasattr(main, "retrieve") and hasattr(main, "chunks"):
        return main
    import app
    return app


def search_docs(query: str, top_k: int = 5):
    """检索文档语料，返回原始 (score, chunk) 列表，供 build_context 使用"""
    app = _runtime()
    _, hits = app.retrieve(query, top_k)
    return hits


def generate_answer(question: str, hits) -> tuple[str, int]:
    """把检索结果交给模型生成答案"""
    app = _runtime()
    return app.generate(app.chat_client, question, app.build_context(hits))


def generate_stream_answer(question: str, hits, usage: dict | None = None):
    """流式版本，供 Streamlit 的 write_stream 使用"""
    app = _runtime()
    usage = usage if usage is not None else {}
    yield from app.generate_stream(app.chat_client, question, app.build_context(hits), usage)


def describe_racket(d: dict) -> str:
    """把结构化结果渲染成文本——纯模板，不经过模型"""
    if not d.get("found"):
        return f"没有找到型号「{d['query']}」的参数。库里现有 34 款，可能不在收录范围内。"

    lines = [f"**{d['brand']} {d['model']}**"]
    for label, key in [("规格", "weights"), ("建议磅数", "tension_raw"),
                       ("击球手感", "stiffness"), ("平衡点", "balance_point"),
                       ("长度", "length"), ("拍框", "frame_material"),
                       ("拍杆", "shaft_material")]:
        v = (d.get(key) or "").strip()
        if v:
            lines.append(f"- {label}：{v}")
    lines.append(f"\n（来源：{d['source']}）")
    return "\n".join(lines)


EQUIP_PROMPT = """你在回答羽毛球装备问题。下面是从装备库查到的**准确参数**。

回答要求：
1. 参数值必须原样引用（磅数、硬度、长度等），**不得改写、不得推测**
2. 用户问「适不适合某种打法 / 水平 / 场景」时，要**基于参数推理并说明依据**是哪几项
3. 参数不足以判断时，明确说出缺什么信息，不要编
4. 中文回答，控制在 150 字以内；不要罗列全部参数（明细会另附）"""


def format_racket_evidence(results: list[dict]) -> str:
    """把装备查询结果整理成证据文本，供模型推理"""
    blocks = []
    for r in results:
        if not r.get("found"):
            blocks.append(f"[装备库] 未收录型号「{r['query']}」")
            continue
        rows = [f"[装备库] {r['brand']} {r['model']}"]
        for label, key in [("规格", "weights"), ("建议磅数", "tension_raw"),
                           ("击球手感", "stiffness"), ("平衡点", "balance_point"),
                           ("长度", "length"), ("拍框", "frame_material"),
                           ("拍杆", "shaft_material")]:
            v = (r.get(key) or "").strip()
            if v:
                rows.append(f"{label}：{v}")
        blocks.append("\n".join(rows))
    return "\n\n".join(blocks)


def generate_equipment_answer(question: str, evidence: str, usage: dict | None = None):
    """基于装备参数生成回答（流式）。参数在 system prompt 里，作为事实约束。"""
    app = _runtime()
    usage = usage if usage is not None else {}
    yield from app.generate_stream(
        app.chat_client, question, evidence, usage, system_prompt=EQUIP_PROMPT
    )


def generate_with_prompt(question: str, evidence: str, system_prompt: str,
                         usage: dict | None = None):
    """通用流式生成：证据 + 自定义 system prompt"""
    app = _runtime()
    usage = usage if usage is not None else {}
    yield from app.generate_stream(
        app.chat_client, question, evidence, usage, system_prompt=system_prompt
    )


if __name__ == "__main__":
    print("=== query_racket: 88S PRO ===")
    print(describe_racket(query_racket("88S PRO")))
    print("\n=== query_racket: 不存在的型号 ===")
    print(describe_racket(query_racket("雷霆99")))
