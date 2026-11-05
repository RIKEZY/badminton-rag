r"""
混合检索验证：一次看清三份结果 + 重叠情况。

跑法（CMD）：
    cd /d F:\WorkPlace\Python\badminton-rag
    .venv\Scripts\python.exe tools/hybrid_check.py
"""

import sys
from pathlib import Path

# 本脚本在 tools/ 下，业务模块在项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os

from dotenv import load_dotenv
from openai import OpenAI

from index_builder import build_chunks, build_vectors
from hybrid import bm25_search_idx, build_bm25, rrf_fuse, vector_search_idx

load_dotenv()

# 想换测试问题就改这里
QUERY = "rally definition"


def show(title: str, hits) -> None:
    print(f"\n{title}")
    for score, idx in hits:
        c = chunks[idx]
        preview = c["text"][:55].replace(chr(10), " ")
        print(f"  {score:.4f}  块{idx:<5} 第{c['page']}页  {preview}")


chunks = build_chunks()
client = OpenAI(
    api_key=os.getenv("SILICONFLOW_API_KEY", "").strip(),
    base_url="https://api.siliconflow.cn/v1",
)
vecs = build_vectors(chunks, client)
bm25 = build_bm25(chunks)

print(f"\n共 {len(chunks)} 块，查询：{QUERY}")

v_hits = vector_search_idx(client, chunks, vecs, QUERY, k=5)
b_hits = bm25_search_idx(bm25, chunks, QUERY, k=5)
fused = rrf_fuse(v_hits, b_hits, top_n=5)

show("向量 top5", v_hits)
show("BM25 top5", b_hits)
show("融合 top5", fused)

# ---- 关键：看融合结果是怎么构成的 ----
v_idx = {i for _, i in v_hits}
b_idx = {i for _, i in b_hits}
fused_idx = [i for _, i in fused]

print("\n" + "=" * 55)
print(f"两路重叠的块      : {sorted(v_idx & b_idx)}")
print(f"只有向量找到的块  : {sorted(v_idx - b_idx)}")
print(f"只有 BM25 找到的块: {sorted(b_idx - v_idx)}")
print(f"融合后返回 {len(fused_idx)} 条（应该是 5 条）")

# 逐条标注来源，验证 RRF 是不是真的在「优先两路都认可的」
print("\n融合结果逐条溯源：")
for rank, (score, idx) in enumerate(fused, 1):
    if idx in v_idx and idx in b_idx:
        src = "两路都命中"
    elif idx in v_idx:
        src = "仅向量"
    else:
        src = "仅 BM25"
    print(f"  {rank}. 块{idx:<5} RRF={score:.4f}  ← {src}")
