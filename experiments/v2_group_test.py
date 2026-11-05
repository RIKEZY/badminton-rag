"""三组对照：验证「拆解只在同侧资源不足时才有效」"""
import sys
from pathlib import Path

# 本项目根与 experiments 目录都要在 sys.path 里：
# 根目录提供 app / index_builder 等业务模块，本目录提供 v2_planner / v2_retrieve
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os

os.environ.setdefault("RAG_TAG", "rules")
os.environ.setdefault("RAG_DATA_DIR", os.path.join(os.path.dirname(__file__), "data_rules_only"))

from dotenv import load_dotenv

load_dotenv()

import app
from v2_retrieve import v2_retrieve

# (组, 问题, 需求1关键词, 需求2关键词)
CASES = [
    ("A", "反手高远球的击球点在哪？正手高远球易犯哪些错误？", "右肩上方", "以肘为轴"),
    ("A", "中管硬度分几档？4U 球拍建议拉多少磅？", "Hi-Flex", "20-28"),
    ("A", "羽毛球的重量范围是多少？球拍的平衡点分几类？", "4.74", "头重"),
    ("B", "网柱放在哪条线上？中管硬度分几档？", "doubles side lines", "Hi-Flex"),
    ("B", "60 秒的间歇什么时候出现？4U 球拍建议拉多少磅？", "60 seconds", "20-28"),
    ("B", "单打发球区怎么定？羽毛球的羽毛长度是多少？", "respective right", "62"),
    ("C", "球拍断了能换吗？比赛允许带几个替补？", None, None),
    ("C", "羽毛球的标准球速是多少？比赛用球是哪个品牌？", None, None),
]


def covered(hits, kw):
    if not kw:
        return None
    return any(kw in c["text"] for _, c in hits)


def fmt(v):
    return "—" if v is None else ("✓" if v else "✗")


print(f"{'组':<3}{'v1 需求1/2':<12}{'v2 需求1/2':<12}{'拆':<4}问题")
print("-" * 78)

stat = {}
for grp, q, kw1, kw2 in CASES:
    _, h1 = app.retrieve(q, 5)
    needs, h2 = v2_retrieve(q, top_k=5)

    v1a, v1b = covered(h1, kw1), covered(h1, kw2)
    v2a, v2b = covered(h2, kw1), covered(h2, kw2)

    print(f"{grp:<3}{fmt(v1a)} / {fmt(v1b):<8}{fmt(v2a)} / {fmt(v2b):<8}{len(needs):<4}{q[:34]}")

    if kw1 or kw2:
        gain = (bool(v2a) + bool(v2b)) - (bool(v1a) + bool(v1b))
        stat.setdefault(grp, []).append(gain)

print("-" * 78)
for grp in ("A", "B"):
    gs = stat.get(grp, [])
    if gs:
        print(f"{grp} 组：v2 相比 v1 平均多覆盖 {sum(gs)/len(gs):+.1f} 个需求")
