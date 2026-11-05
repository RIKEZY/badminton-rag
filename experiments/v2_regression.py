"""v2 回归测试：10 题评测，确认拆解不破坏原有能力"""
import sys
from pathlib import Path

# 本项目根与 experiments 目录都要在 sys.path 里：
# 根目录提供 app / index_builder 等业务模块，本目录提供 v2_planner / v2_retrieve
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os
import time

# 必须在任何业务模块之前设置——index_builder 在 import 时就固化 TAG，
# 晚于 run_eval/app 的 import 会导致加载成全语料（274 块）而非规则集（82 块）
os.environ.setdefault("RAG_TAG", "rules")
os.environ.setdefault("RAG_DATA_DIR", os.path.join(os.path.dirname(__file__), "data_rules_only"))

from dotenv import load_dotenv

load_dotenv()

import app
from run_eval import EVAL_SET
from v2_retrieve import v2_retrieve

print(f"[检查] 语料块数 = {len(app.chunks)}（应为 82）\n")


def is_hit(hits, expected) -> bool:
    for _, c in hits:
        for src, page, kw in expected:
            if c["source"] == src and c["page"] == page and kw in c["text"]:
                return True
    return False


hits_ok = 0
rows = []
t_all = time.time()

for i, (q, expected) in enumerate(EVAL_SET, 1):
    t0 = time.time()
    needs, hits = v2_retrieve(q, top_k=5)
    dt = time.time() - t0
    ok = is_hit(hits, expected)
    hits_ok += ok
    rows.append((i, q, len(needs), ok, dt))

    flag = "OK " if ok else "MISS"
    print(f"[{flag}] #{i:<2} 需求{len(needs)} {dt:5.2f}s  {q[:30]}")
    if len(needs) > 1:
        for n in needs:
            print(f"          └ {n}")

total = time.time() - t_all
print("-" * 60)
print(f"Recall@5: {hits_ok}/{len(EVAL_SET)}")
print(f"总耗时: {total:.1f}s  平均 {total/len(EVAL_SET):.2f}s/题")
multi = [r for r in rows if r[2] > 1]
print(f"被拆解的题: {len(multi)} 道 {[(r[0], r[2]) for r in multi]}")
