"""检查同一问题多次检索的结果是否一致

怀疑点：改写有非确定性，可能导致同一问题每次检索结果不同。
若成立，所有评测都有噪声，单次结果不可信。
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

Q = "一局结束后什么时候换边？"
TARGET = [18, 460]          # 含换边规则的块

print(f"问题：{Q}")
print(f"答案块：{TARGET}\n")

for run in range(1, 4):
    queries, hits = app.retrieve(Q, 5)
    idxs = [app.chunks.index(c) for _, c in hits]
    hit = [i for i in TARGET if i in idxs]
    print(f"第 {run} 次：top5 = {idxs}  命中={hit or '无'}")
    for i, q in enumerate(queries, 1):
        print(f"         改写{i}: {q[:70]}")
    print()
