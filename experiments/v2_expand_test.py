"""扩样本：4 道复合题，v1 vs v2 对照"""
import sys
from pathlib import Path

# 本项目根与 experiments 目录都要在 sys.path 里：
# 根目录提供 app / index_builder 等业务模块，本目录提供 v2_planner / v2_retrieve
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os
import time

os.environ.setdefault("RAG_TAG", "rules")
os.environ.setdefault("RAG_DATA_DIR", os.path.join(os.path.dirname(__file__), "data_rules_only"))

from dotenv import load_dotenv

load_dotenv()

import app
from v2_retrieve import v2_retrieve

QS = [
    "球拍的长度限制是多少？发球时击球点有什么高度要求？",
    "比赛间歇时能接受指导吗？球拍断了能换吗？",
    "反手高远球的握拍要领是什么？中管硬度分几档？",
    "单打边线和双打边线有什么区别？发球区错误怎么判？",
]

for q in QS:
    print("=" * 70)
    print(f"问题：{q}")

    t0 = time.time()
    _, v1_hits = app.retrieve(q, 5)
    a1, t1 = app.generate(app.chat_client, q, app.build_context(v1_hits))
    d1 = time.time() - t0

    t0 = time.time()
    needs, v2_hits = v2_retrieve(q, top_k=5)
    a2, t2 = app.generate(app.chat_client, q, app.build_context(v2_hits))
    d2 = time.time() - t0

    print(f"拆解：{len(needs)} 个需求")
    for i, n in enumerate(needs, 1):
        print(f"  {i}. {n}")
    print(f"v1 来源：{sorted({c['source'][:12] for _, c in v1_hits})}")
    print(f"v2 来源：{sorted({c['source'][:12] for _, c in v2_hits})}")
    print(f"\n--- v1（{d1:.1f}s / {t1}t / {len(a1)}字）---")
    print(a1[:260].replace("\n", " "))
    print(f"\n--- v2（{d2:.1f}s / {t2}t / {len(a2)}字）---")
    print(a2[:260].replace("\n", " "))
    print()
