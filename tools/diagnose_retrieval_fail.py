"""诊断「检索失败」：语料里有答案，为什么检索不到

以「一局结束后什么时候换边」为例，逐步展示：
    1. 语料里正确答案在哪一块
    2. 改写把问题变成了什么
    3. 实际检索命中了什么
    4. 差距出在哪一环
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
from hybrid import bm25_search_idx, vector_search_idx

Q = "一局结束后什么时候换边？"

print("=" * 84)
print("第 1 步：语料里到底有没有答案")
print("=" * 84)
cs = json.loads((ROOT / "chunks_v2.json").read_text(encoding="utf-8"))
found = [c for c in cs if "change ends" in c["text"].lower() or "change of ends" in c["text"].lower()]
print(f"  含 change ends / change of ends 的块：{len(found)} 个")
for c in found:
    idx = cs.index(c)
    print(f"\n  ── 块 #{idx} [{c['doc_type']}] {c['source']} p{c['page']} ──")
    print(f"  {c['text'][:300].replace(chr(10), ' ')}")

print("\n" + "=" * 84)
print("第 2 步：问题被改写成什么")
print("=" * 84)
queries = app.rewrite_queries(app.chat_client, Q)
print(f"  原问：{Q}")
for i, q in enumerate(queries, 1):
    print(f"  改写 {i}：{q}")

print("\n" + "=" * 84)
print("第 3 步：各路检索分别命中了什么")
print("=" * 84)

for name, hits in [
    ("中文向量", vector_search_idx(app.embed_client, app.chunks, app.vecs, Q, k=5)),
    ("中文 BM25", bm25_search_idx(app.bm25, app.chunks, Q, k=5)),
]:
    print(f"\n  【{name}】")
    for rank, (score, idx) in enumerate(hits, 1):
        c = app.chunks[idx]
        mark = "  ← 答案" if ("change ends" in c["text"].lower()
                             or "change of ends" in c["text"].lower()) else ""
        print(f"    {rank}. {score:.4f} #{idx} [{c['doc_type']}] {c['source'][:16]}p{c['page']}{mark}")

print("\n" + "=" * 84)
print("第 4 步：最终 top5（重排后）")
print("=" * 84)
_, final = app.retrieve(Q, 5)
for rank, (score, c) in enumerate(final, 1):
    mark = "  ← 答案" if ("change ends" in c["text"].lower()
                         or "change of ends" in c["text"].lower()) else ""
    print(f"  {rank}. rerank={score:.4f} [{c['doc_type']}] {c['source'][:18]}p{c['page']}{mark}")
    print(f"     {c['text'][:110].replace(chr(10), ' ')}")

print("\n" + "=" * 84)
print("第 5 步：诊断")
print("=" * 84)
ans_idx = [cs.index(c) for c in found]
final_idx = [app.chunks.index(c) for _, c in final]
hit = [i for i in ans_idx if i in final_idx]
print(f"  正确答案所在块：{ans_idx}")
print(f"  最终 top5 块号：{final_idx}")
print(f"  是否命中：{'是' if hit else '否'}")
