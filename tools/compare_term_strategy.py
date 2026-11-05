"""对比两种术语策略

A. 现状：prompt 约束（改写里带术语）+ 术语独立成一路 BM25
B. 你的方案：检测到术语后，强制把术语拼进每条改写

关键差异：B 让术语进入 6 路改写投票，A 只有 1 路术语单独投票。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RAG_TAG", "v2")
os.environ.setdefault("RAG_DATA_DIR", str(ROOT / "data_rules_only"))
os.environ["RAG_RERANK"] = "true"

from dotenv import load_dotenv

load_dotenv()

import app
from hybrid import bm25_search_idx

CASES = [
    ("一局结束后什么时候换边？", [18, 460]),
    ("球落在边线上算出界吗？", [27, 469]),
    ("比赛中可以要求擦汗吗？", [397]),
]

for q, target in CASES:
    print("=" * 82)
    print(f"问题：{q}")
    print(f"答案块：{target}")

    terms = app.term_queries(q)
    queries = app.rewrite_queries(app.chat_client, q)

    print(f"\n  术语识别：{terms or '（无）'}")
    print(f"  原始改写：")
    for i, x in enumerate(queries, 1):
        hits = bm25_search_idx(app.bm25, app.chunks, x, k=5)
        idxs = [j for _, j in hits]
        ok = [t for t in target if t in idxs]
        print(f"    {i}. {x[:74]}")
        print(f"       BM25 top5={idxs}  {'✅' + str(ok) if ok else '❌'}")

    if terms:
        suffix = " ".join(terms)
        print(f"\n  拼接术语后（+ {suffix!r}）：")
        for i, x in enumerate(queries, 1):
            aug = f"{x} {suffix}"
            hits = bm25_search_idx(app.bm25, app.chunks, aug, k=5)
            idxs = [j for _, j in hits]
            ok = [t for t in target if t in idxs]
            print(f"    {i}. …{x[-40:]}")
            print(f"       BM25 top5={idxs}  {'✅' + str(ok) if ok else '❌'}")
    print()
