"""核实候选题：看 top3 命中块的实际内容，确认答案存在并确定判定关键词"""
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

QS = [
    ("A5", "球落在边线上算出界吗？"),
    ("A4", "比赛中球员可以要求擦汗或喝水吗？"),
    ("A2", "一局结束后什么时候换边？"),
    ("B2", "网前搓球的技术要点是什么？"),
    ("E2", "奥运会羽毛球积分怎么算？"),
    ("A1", "21 分制下 20 平之后怎么算赢？"),
    ("A3", "发球时球拍必须朝下吗？"),
    ("B1", "正手挑球和反手挑球有什么区别？"),
    ("C1", "新手应该选 3U 还是 4U 的球拍？"),
    ("C2", "球线磅数越高越好吗？"),
    ("C4", "羽毛球拍的平衡点怎么影响打法？"),
    ("D1", "裁判出示黄牌是警告还是罚分？"),
    ("D3", "司线裁判判错了可以改判吗？"),
    ("E1", "世界巡回赛分几个级别？"),
    ("E4", "比赛种子怎么排？"),
    ("F1", "间歇时裁判需要做什么，规则怎么规定的？"),
    ("F2", "球拍尺寸有规定吗，88S PRO 符合标准吗？"),
]

for code, q in QS:
    _, hits = app.retrieve(q, 3)
    print("=" * 96)
    print(f"[{code}] {q}")
    for i, (score, c) in enumerate(hits, 1):
        txt = c["text"].replace("\n", " ")[:170]
        print(f"  {i}. {score:.3f} [{c.get('doc_type','?')}] {c['source']} p{c['page']}")
        print(f"     {txt}")
