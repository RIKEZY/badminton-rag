"""重新验证 9 个缺口题：到底是语料缺失，还是检索失败

关键改进：不看 top1 分数，而是检查「含答案关键词的块」是否在 top5 里。
之前用 top1 分数判断是错的——换边那题 top1 只有 0.20，
但正确答案在 top3/top4，实际是命中的。
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

cs = json.loads((ROOT / "chunks_v2.json").read_text(encoding="utf-8"))

GAPS = [
    ("一局结束后什么时候换边？", "Players shall change ends"),
    ("裁判出示黄牌是警告还是罚分？", "yellow card"),
    ("球落在边线上算出界吗？", "base of the shuttle"),
    ("比赛中球员可以要求擦汗或喝水吗？", "towel"),
    ("网前搓球的技术要点是什么？", "net shot"),
    ("球线磅数越高越好吗？", "string tension"),
    ("打球老是打不到球怎么办？", None),
    ("拍子太重要不要换一个？", None),
    ("双打老是撞拍怎么办？", None),
]

print(f"{'问题':<24}{'答案块':<14}{'top5 命中':<12}{'结论'}")
print("-" * 80)

for q, kw in GAPS:
    if kw is None:
        print(f"{q[:22]:<24}{'—':<14}{'—':<12}语料缺失（无对应关键词）")
        continue
    idxs = [i for i, c in enumerate(cs) if kw.lower() in c["text"].lower()]
    _, hits = app.retrieve(q, 5)
    top_idx = [app.chunks.index(c) for _, c in hits]
    overlap = [i for i in idxs if i in top_idx]
    if not idxs:
        verdict = "语料缺失"
    elif overlap:
        verdict = f"✅ 检索成功"
    else:
        verdict = "❌ 检索失败"
    print(f"{q[:22]:<24}{str(idxs[:3]):<14}{str(overlap):<12}{verdict}")

print("\n" + "=" * 80)
print("说明：判定关键词需从语料原文复制，不能凭记忆写。")
