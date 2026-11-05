"""核对探测中分数异常的题目：看 top1 的实际内容，判断语料到底有没有答案"""
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

SUSPECT = [
    ("A11", "裁判可以出示哪几种牌？", "可答"),
    ("A16", "世界纪录最快杀球速度是多少？", "拒答"),
    ("A19", "羽毛球运动起源于哪个国家？", "拒答"),
    ("B9", "鹰眼挑战有次数限制吗？", "可答"),
    ("B16", "打球老是打不到球怎么办？", "拒答"),
    ("B17", "拍子太重要不要换一个？", "拒答"),
    ("C7", "奥运会资格怎么获得，积分要求是什么？", "可答"),
    ("C16", "我该买哪款球拍？", "拒答"),
    ("D8", "一局比赛中最多可以换几次球？", "可答"),
    ("D16", "网前搓球的技术要点是什么？", "拒答"),
    ("D20", "反手过渡球怎么打？", "拒答"),
]

for code, q, expect in SUSPECT:
    _, hits = app.retrieve(q, 2)
    print("=" * 90)
    print(f"[{code}] {q}   （期望：{expect}）")
    for i, (s, c) in enumerate(hits, 1):
        print(f"  {i}. {s:.3f} [{c['doc_type']}] {c['source']} p{c['page']}")
        print(f"     {c['text'][:220].replace(chr(10), ' ')}")
    print()
