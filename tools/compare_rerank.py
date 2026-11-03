"""重排对照实验：各跑 3 次取平均

单次运行波动明显（改写有非确定性），必须重复。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RAG_TAG", "v2")
os.environ.setdefault("RAG_DATA_DIR", str(ROOT / "data_rules_only"))

from dotenv import load_dotenv

load_dotenv()

import app
from run_eval import EVAL_SET
from tools.eval_new import EVAL_V2


def is_hit(hits, expected):
    for _, c in hits:
        for src, page, kw in expected:
            if c["source"] == src and c["page"] == page and kw in c["text"]:
                return True
    return False


def one_round(cases):
    ok = 0
    for item in cases:
        _, hits = app.retrieve(item[0], 5)
        ok += is_hit(hits, item[1])
    return ok


OLD = [(q, e) for q, e in EVAL_SET]
NEW = [(q, e) for q, e, *_ in EVAL_V2]
ALL = OLD + NEW

print(f"语料 {len(app.chunks)} 块 | 重排={'开' if app.RERANK_ENABLED else '关'} | pool={app.RERANK_POOL}")
print(f"题量：老 {len(OLD)} + 新 {len(NEW)} = {len(ALL)}\n")

runs = []
for i in range(3):
    o = one_round(OLD)
    n = one_round(NEW)
    runs.append((o, n))
    print(f"  第 {i + 1} 次：老 {o}/{len(OLD)}  新 {n}/{len(NEW)}  合计 {o + n}/{len(ALL)}")

avg_old = sum(r[0] for r in runs) / 3
avg_new = sum(r[1] for r in runs) / 3
print(f"\n平均：老 {avg_old:.1f}/{len(OLD)}  新 {avg_new:.1f}/{len(NEW)}  "
      f"合计 {avg_old + avg_new:.1f}/{len(ALL)} = {(avg_old + avg_new) / len(ALL) * 100:.0f}%")
