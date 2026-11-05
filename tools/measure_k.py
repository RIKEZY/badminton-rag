"""测量 Recall@k 曲线与重排分数分布

回答两个问题：
    1. 最终 top_k 取多少合适？—— 看 Recall@k 在哪里趋平
    2. 能不能用重排分数的断崖来动态定 top_n？—— 看分数分布有没有明显断崖
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RAG_TAG", "v2")
os.environ.setdefault("RAG_DATA_DIR", str(ROOT / "data_rules_only"))
os.environ["RAG_RERANK"] = "true"
os.environ["RERANK_POOL"] = "30"      # 要测到 30，池子必须够

from dotenv import load_dotenv

load_dotenv()

import app
from run_eval import EVAL_SET
from tools.eval_new import EVAL_V2

CASES = [(q, e) for q, e in EVAL_SET] + [(q, e) for q, e, *_ in EVAL_V2]
KS = [1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 30]


def match(chunk, expected) -> bool:
    for src, page, kw in expected:
        if chunk["source"] == src and chunk["page"] == page and kw in chunk["text"]:
            return True
    return False


rows = []
for i, (q, expected) in enumerate(CASES, 1):
    _, hits = app.retrieve(q, 30)
    rank = next((r for r, (_, c) in enumerate(hits, 1) if match(c, expected)), None)
    scores = [round(s, 4) for s, _ in hits[:10]]
    rows.append({"q": q, "rank": rank, "scores": scores})
    print(f"[{i:>2}/{len(CASES)}] 正确块排名={rank or '未命中':<4} {q[:34]}", flush=True)

print("\n" + "=" * 74)
print("Recall@k")
print("=" * 74)
n = len(rows)
for k in KS:
    hit = sum(1 for r in rows if r["rank"] and r["rank"] <= k)
    bar = "█" * round(hit / n * 40)
    print(f"  k={k:<3} {hit:>2}/{n} = {hit / n * 100:>5.1f}%  {bar}")

print("\n" + "=" * 74)
print("重排分数分布（前 6 名）—— 看有没有断崖")
print("=" * 74)
gaps = []
for r in rows:
    s = r["scores"][:6]
    if len(s) < 2:
        continue
    diffs = [round(s[i] - s[i + 1], 3) for i in range(len(s) - 1)]
    top_gap = max(diffs)
    gap_at = diffs.index(top_gap) + 1        # 断崖在第 gap_at 和第 gap_at+1 名之间
    gaps.append((top_gap, gap_at, r["q"][:26], s))
    print(f"  最大断层 {top_gap:.3f} 在第 {gap_at}→{gap_at + 1} 名  {r['q'][:26]}")
    print(f"      分数 {s}")

print("\n" + "=" * 74)
print("断崖法可行性：正确答案是否总在断崖之前？")
print("=" * 74)
print(f"  {'正确块排名':<10}{'断崖位置':<10}{'安全?':<8}问题")
safe = 0
for g, r in zip(gaps, [x for x in rows if len(x["scores"]) >= 2]):
    top_gap, gap_at, q, s = g
    rank = r["rank"]
    ok = rank is not None and rank <= gap_at
    safe += ok
    print(f"  {str(rank):<10}{gap_at:<10}{'OK' if ok else 'X 会切掉':<8}{q}")

print(f"\n  断崖法安全率：{safe}/{len(gaps)} = {safe / len(gaps) * 100:.0f}%")
print("  说明：若安全率低，说明正确答案有时排在断崖之后，按断崖切会丢掉答案。")

print("\n" + "=" * 74)
print("断崖统计")
print("=" * 74)
big = [g for g in gaps if g[0] >= 0.1]
print(f"  断层 >= 0.1 的题：{len(big)}/{len(gaps)}")
print(f"  断层 >= 0.05 的题：{len([g for g in gaps if g[0] >= 0.05])}/{len(gaps)}")
print(f"  断崖位置分布：{sorted(g[1] for g in gaps)}")
print(f"  断崖位置平均：{sum(g[1] for g in gaps) / len(gaps):.1f} 块")
