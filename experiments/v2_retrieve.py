"""V2 检索：先拆需求，再分别检索，轮转合并

合并策略说明（关键设计）：
    不同需求的 RRF 分数不可比——需求 A 的第 1 名和需求 B 的第 1 名，
    分数高低只反映各自候选池的竞争激烈程度，不反映相关性。
    所以合并时不用分数排序，而用「轮转」：
        A1, B1, C1, A2, B2, C2 ...
    保证每个需求都有代表进最终结果，避免高分需求把低分需求的证据全挤掉
    （这正是 v1 里块 67 被挤掉的原因）。
"""
import sys
from pathlib import Path

# 本项目根与 experiments 目录都要在 sys.path 里：
# 根目录提供 app / index_builder 等业务模块，本目录提供 v2_planner / v2_retrieve
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import retrieve
from v2_planner import split_needs


def chunk_key(c: dict) -> tuple:
    """同一块的判定：来源 + 页码 + 正文前 60 字"""
    return (c["source"], c["page"], c["text"][:60])


def v2_retrieve(question: str, top_k: int = 5, per_need: int = 3):
    """返回 (拆出的需求列表, [(分数, 块), ...])"""
    needs = split_needs(question)

    # 单需求：直接走 v1，行为完全不变（零回归风险）
    if len(needs) == 1:
        _, hits = retrieve(question, top_k)
        return needs, hits

    # 每个需求独立检索（retrieve 返回 (queries, hits)，这里只要 hits）
    per_need_hits = [retrieve(n, per_need)[1] for n in needs]

    # 轮转合并 + 去重（同一块被多个需求命中时，保留最先出现的）
    merged, seen = [], set()
    for rank in range(per_need):
        for hits in per_need_hits:
            if rank >= len(hits):
                continue
            score, chunk = hits[rank]
            key = chunk_key(chunk)
            if key in seen:
                continue
            seen.add(key)
            merged.append((score, chunk))

    return needs, merged[:top_k]


if __name__ == "__main__":
    CASES = [
        ("球拍和羽毛球分别有哪些规格限制？", "块67（羽毛球规格）"),
        ("单打和双打的发球区边界有什么不同？", "对比题，应保持 1 个需求"),
    ]

    for q, note in CASES:
        print("=" * 64)
        print(f"问题：{q}")
        print(f"备注：{note}")

        needs, hits = v2_retrieve(q)
        print(f"拆出 {len(needs)} 个需求：")
        for i, n in enumerate(needs, 1):
            print(f"  {i}. {n}")

        print(f"v2 top{len(hits)}：")
        for pos, (score, c) in enumerate(hits, 1):
            print(f"  {pos}. [{c.get('doc_type', '?')}] {c['source'][:16]} p{c['page']}"
                  f"  {c['text'][:38].replace(chr(10), ' ')}")
        print()
