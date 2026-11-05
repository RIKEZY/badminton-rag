"""候选评测题：先跑一遍检索，看每道题在语料里有没有答案

用途：避免出「语料里根本没有」的题当正样本，
      也避免出「语料里其实有」的题当负样本。
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

# (编号, 分类, 问题)
CANDIDATES = [
    # A 规则
    ("A1", "规则", "21 分制下 20 平之后怎么算赢？"),
    ("A2", "规则", "一局结束后什么时候换边？"),
    ("A3", "规则", "发球时球拍必须朝下吗？"),
    ("A4", "规则", "比赛中球员可以要求擦汗或喝水吗？"),
    ("A5", "规则", "球落在边线上算出界吗？"),
    # B 技术
    ("B1", "技术", "正手挑球和反手挑球有什么区别？"),
    ("B2", "技术", "网前搓球的技术要点是什么？"),
    ("B3", "技术", "杀球之后怎么快速回中？"),
    ("B4", "技术", "正手吊球和劈吊有什么区别？"),
    # C 装备
    ("C1", "装备", "新手应该选 3U 还是 4U 的球拍？"),
    ("C2", "装备", "球线磅数越高越好吗？"),
    ("C3", "装备", "ASTROX 88S PRO 和 88D TOUR 有什么区别？"),
    ("C4", "装备", "羽毛球拍的平衡点怎么影响打法？"),
    # D 裁判
    ("D1", "裁判", "裁判出示黄牌是警告还是罚分？"),
    ("D2", "裁判", "球员可以要求裁判换球吗？"),
    ("D3", "裁判", "司线裁判判错了可以改判吗？"),
    # E 赛事
    ("E1", "赛事", "世界巡回赛分几个级别？"),
    ("E2", "赛事", "奥运会羽毛球积分怎么算？"),
    ("E3", "赛事", "团体赛可以带几名替补？"),
    ("E4", "赛事", "比赛种子怎么排？"),
    # F 跨文档
    ("F1", "跨文档", "间歇时裁判需要做什么，规则怎么规定的？"),
    ("F2", "跨文档", "球拍尺寸有规定吗，88S PRO 符合标准吗？"),
    # G 负样本（语料里应该没有）
    ("G1", "负样本", "2028 年奥运会羽毛球比赛在哪个场馆？"),
    ("G2", "负样本", "林丹拿过几次世锦赛冠军？"),
    ("G3", "负样本", "中国国家队现任主教练是谁？"),
    # H 口语化
    ("H1", "口语", "打球老是打不到球怎么办？"),
    ("H2", "口语", "拍子太重要不要换一个？"),
    ("H3", "口语", "双打老是撞拍怎么办？"),
]

print(f"{'编号':<5}{'分类':<8}{'最高分':<8}{'top1 来源':<22}{'问题'}")
print("-" * 96)

for code, cat, q in CANDIDATES:
    try:
        _, hits = app.retrieve(q, 5)
        top_score, top_c = hits[0]
        src = f"{top_c['source'][:16]}p{top_c['page']}"
        flag = ""
        if top_score < 0.15:
            flag = "  ⚠️ 低分"
        elif top_score < 0.35:
            flag = "  ? 中等"
        print(f"{code:<5}{cat:<8}{top_score:<8.3f}{src:<22}{q[:30]}{flag}", flush=True)
    except Exception as e:
        print(f"{code:<5}{cat:<8}{'ERR':<8}{'':<22}{q[:30]}  {type(e).__name__}", flush=True)
