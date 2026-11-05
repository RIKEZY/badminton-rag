"""完整链路追踪：抓每一步的中间数据，用于画流程图

以「一局结束后什么时候换边？」为例，覆盖：
    改写（含术语注入）→ 三组检索 → 语言内 RRF → 跨语言 RRF → 重排 → 输出
"""
import json
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
from hybrid import bm25_search_idx, fuse_by_language, vector_search_idx
from rerank import rerank

Q = "一局结束后什么时候换边？"
POOL = app.RERANK_POOL
TARGET = [18, 460]

print("=" * 78)
print(f"问题：{Q}")
print(f"答案块：{TARGET}")
print("=" * 78)

# 1 改写
queries = app.rewrite_queries(app.chat_client, Q)
print("\n【第 1 步】改写（注入术语表后）")
for i, q in enumerate(queries, 1):
    print(f"  改写 {i}：{q}")

# 2 术语识别
terms = app.term_queries(Q)
print(f"\n【第 2 步】术语识别")
print(f"  中文术语命中 → {terms}")

# 3 三组检索
print("\n【第 3 步】三组检索")
zh = [vector_search_idx(app.embed_client, app.chunks, app.vecs, Q, k=POOL),
      bm25_search_idx(app.bm25, app.chunks, Q, k=POOL)]
print(f"  中文侧 2 路：向量 top3={[i for _, i in zh[0][:3]]}  "
      f"BM25 top3={[i for _, i in zh[1][:3]]}")

en = []
for q in queries:
    en.append(vector_search_idx(app.embed_client, app.chunks, app.vecs, q, k=POOL))
    en.append(bm25_search_idx(app.bm25, app.chunks, q, k=POOL))
print(f"  英文侧 {len(en)} 路（3 改写 × 2）：")
for i in range(0, len(en), 2):
    print(f"    改写{i // 2 + 1} 向量 top3={[x for _, x in en[i][:3]]}  "
          f"BM25 top3={[x for _, x in en[i + 1][:3]]}")

term = [bm25_search_idx(app.bm25, app.chunks, t, k=POOL) for t in terms]
print(f"  术语侧 {len(term)} 路：")
for t, hits in zip(terms, term):
    print(f"    BM25({t!r}) top3={[i for _, i in hits[:3]]}")

# 4 两级 RRF
print("\n【第 4 步】两级 RRF 融合")
fused = fuse_by_language(zh, en, top_n=POOL, term_hit_lists=term)
cand = [i for _, i in fused]
print(f"  候选池 {len(cand)} 个：{cand[:10]}...")
print(f"  答案块是否进入候选池：{[i for i in TARGET if i in cand]}")

# 5 重排
print("\n【第 5 步】重排")
ranked = rerank(Q, [app.chunks[i]["text"] for i in cand], top_n=POOL)
print(f"  重排后前 6：")
for k, (i, s) in enumerate(ranked[:6], 1):
    ci = cand[i]
    mark = " ← 答案" if ci in TARGET else ""
    c = app.chunks[ci]
    print(f"    {k}. {s:.4f} 块#{ci} [{c['doc_type']}] {c['source'][:16]}{mark}")

# 6 输出
print("\n【第 6 步】最终 top5")
_, final = app.retrieve(Q, 5)
for k, (s, c) in enumerate(final, 1):
    ci = app.chunks.index(c)
    mark = " ← 答案" if ci in TARGET else ""
    print(f"  {k}. {s:.4f} 块#{ci} [{c['doc_type']}] {c['source'][:16]} p{c['page']}{mark}")

print("\n【第 7 步】生成回答")
answer = "".join(app.generate_stream(app.chat_client, Q,
                                     app.build_context(final), {}, system_prompt=None))
print(f"  {answer[:200]}")
