"""看拒答题的检索最高分分布，用来定「低相关」阈值

拒答题的正确行为是承认不知道。但如果模型看到的证据分数并不低（语义相关、
但不回答问题），它就容易硬凑答案。这个脚本量一下这批题到底多少分。
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

REFUSE_Q = [
    "安赛龙的身高是多少？",
    "林丹拿过几次世锦赛冠军？",
    "双打老是撞拍怎么办？",
    "打球膝盖疼怎么办？",
    "尤尼克斯和李宁哪个好？",
    "现在男单世界第一是谁？",
    "2028 年奥运会羽毛球在哪个场馆？",
    "混双站位怎么配合？",
    "杀球之后怎么快速回中？",
]

# 对照组：能答对的题，它们的分数应该明显更高
ANSWERABLE_Q = [
    "发球时击球点必须在多高以下？",
    "一局结束后什么时候换边？",
    "反手高远球的击球点在哪？",
    "球落在边线上算出界吗？",
]

print(f"{'类型':<6}{'最高分':<10}{'问题'}")
print("-" * 66)
ref_scores, ans_scores = [], []
for q in REFUSE_Q:
    _, hits = app.retrieve(q, 5)
    top = max((s for s, _ in hits), default=0.0)
    ref_scores.append(top)
    print(f"{'拒答':<6}{top:<10.4f}{q}")

print()
for q in ANSWERABLE_Q:
    _, hits = app.retrieve(q, 5)
    top = max((s for s, _ in hits), default=0.0)
    ans_scores.append(top)
    print(f"{'可答':<6}{top:<10.4f}{q}")

print()
print(f"拒答题最高分：min={min(ref_scores):.4f}  max={max(ref_scores):.4f}  "
      f"avg={sum(ref_scores)/len(ref_scores):.4f}")
print(f"可答题最高分：min={min(ans_scores):.4f}  max={max(ans_scores):.4f}  "
      f"avg={sum(ans_scores)/len(ans_scores):.4f}")
