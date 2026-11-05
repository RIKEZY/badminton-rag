"""四组 × 20 题全量探测（重新跑，不复用旧结果）

每组 15 道可答 + 5 道拒答。判定标准：
    可答题：top1 分数应 >= 0.5，且来源合理
    拒答题：top1 分数应 < 0.3（语料确实没有）

分数只作初筛，最终判定要人工核对原文。
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

# (编号, 问题, 是否可答)
GROUPS = {
    "A 单点事实": [
        ("A1", "发球时击球点必须在多高以下？", True),
        ("A2", "网柱应该有多高？", True),
        ("A3", "羽毛球有多少根羽毛？", True),
        ("A4", "局间休息多少秒？", True),
        ("A5", "球拍总长度上限是多少？", True),
        ("A6", "连击的定义是什么？", True),
        ("A7", "什么叫死球？", True),
        ("A8", "裁判用语里的 Let 是什么意思？", True),
        ("A9", "什么是发球区错误？", True),
        ("A10", "发球违例有哪些情形？", True),
        ("A11", "裁判可以出示哪几种牌？", True),
        ("A12", "世界巡回赛分几个级别？", True),
        ("A13", "什么情况下判重发球？", True),
        ("A14", "什么情况下球员会被取消资格？", True),
        ("A15", "球落在边线上算出界吗？", True),
        ("A16", "世界纪录最快杀球速度是多少？", False),
        ("A17", "安赛龙的身高是多少？", False),
        ("A18", "林丹拿过几次世锦赛冠军？", False),
        ("A19", "羽毛球运动起源于哪个国家？", False),
        ("A20", "一场比赛平均多长时间？", False),
    ],
    "B 口语化": [
        ("B1", "拍子能有多长？", True),
        ("B2", "球毛掉了还能打吗？", True),
        ("B3", "换场是怎么换的？", True),
        ("B4", "中场休息能有多久？", True),
        ("B5", "为什么我发球老是被判犯规？", True),
        ("B6", "打到 20 平还要打几分？", True),
        ("B7", "一局打完休息多久？", True),
        ("B8", "比赛打到一半想上厕所怎么办？", True),
        ("B9", "鹰眼挑战有次数限制吗？", True),
        ("B10", "什么是 IRS？", True),
        ("B11", "什么是 GCR？", True),
        ("B12", "什么情况下会用 yellow card？", True),
        ("B13", "发球时球拍要高于手腕吗？", True),
        ("B14", "双打搭档可以连续击球吗？", True),
        ("B15", "比赛中间可以叫暂停吗？", True),
        ("B16", "打球老是打不到球怎么办？", False),
        ("B17", "拍子太重要不要换一个？", False),
        ("B18", "双打老是撞拍怎么办？", False),
        ("B19", "手腕力量怎么练？", False),
        ("B20", "打球膝盖疼怎么办？", False),
    ],
    "C 跨文档": [
        ("C1", "间歇时裁判要做什么，规则怎么规定？", True),
        ("C2", "发球违例有哪些，裁判怎么判？", True),
        ("C3", "换球的规定是什么，裁判怎么操作？", True),
        ("C4", "球员行为不当会被怎么处罚？", True),
        ("C5", "裁判可以改判司线的判罚吗？", True),
        ("C6", "赛事分几个级别，各自积分多少？", True),
        ("C7", "奥运会资格怎么获得，积分要求是什么？", True),
        ("C8", "种子怎么排，依据是什么？", True),
        ("C9", "球拍尺寸有规定吗，88S PRO 符合吗？", True),
        ("C10", "羽毛球的标准重量和尺寸是多少？", True),
        ("C11", "球拍中管硬度分几档，各适合什么水平？", True),
        ("C12", "场地规格有哪些要求，网柱怎么固定？", True),
        ("C13", "裁判长和主裁的职责怎么分？", True),
        ("C14", "退赛会有什么后果？", True),
        ("C15", "世界排名、种子排位和抽签之间是什么关系？", True),
        ("C16", "我该买哪款球拍？", False),
        ("C17", "尤尼克斯和李宁哪个好？", False),
        ("C18", "现在男单世界第一是谁？", False),
        ("C19", "2028 年奥运会羽毛球在哪个场馆？", False),
        ("C20", "业余选手多久能到中级水平？", False),
    ],
    "D 深度细节": [
        ("D1", "3U 和 4U 的球拍差多少克？", True),
        ("D2", "平衡点分几类，各适合什么打法？", True),
        ("D3", "同一型号 3U 和 4U 的磅数上限差多少？", True),
        ("D4", "发球裁判的职责有哪些？", True),
        ("D5", "主裁在什么情况下会请裁判长进场？", True),
        ("D6", "司线裁判判罚的依据是什么？", True),
        ("D7", "裁判的判罚是最终的吗，有没有例外？", True),
        ("D8", "一局比赛中最多可以换几次球？", True),
        ("D9", "比赛中球坏了怎么处理？", True),
        ("D10", "发球时球拍必须朝下吗？", True),
        ("D11", "过网击球的判定标准是什么？", True),
        ("D12", "触网算不算违例？", True),
        ("D13", "球触天花板怎么判？", True),
        ("D14", "比赛用球的速度怎么测试？", True),
        ("D15", "发球区错误会怎么判？", True),
        ("D16", "网前搓球的技术要点是什么？", False),
        ("D17", "正手吊球和劈吊有什么区别？", False),
        ("D18", "杀球之后怎么快速回中？", False),
        ("D19", "混双站位怎么配合？", False),
        ("D20", "反手过渡球怎么打？", False),
    ],
}

suspect = []

for gname, items in GROUPS.items():
    print("=" * 90)
    print(f"{gname}")
    print("=" * 90)
    print(f"  {'编号':<6}{'分':<7}{'期望':<6}{'实际':<6}{'top1 来源':<18}问题")
    for code, q, answerable in items:
        try:
            _, hits = app.retrieve(q, 5)
            s, c = hits[0]
            expect = "可答" if answerable else "拒答"
            if answerable:
                ok = s >= 0.5
                actual = "有" if ok else "低"
            else:
                ok = s < 0.3
                actual = "无" if ok else "高"
            if not ok:
                suspect.append((code, q, expect, s, c["source"]))
            print(f"  {code:<6}{s:<7.3f}{expect:<6}{actual:<6}{c['source'][:16]:<18}{q[:26]}", flush=True)
        except Exception as e:
            print(f"  {code:<6}{'ERR':<7}{'':<6}{'':<6}{'':<18}{q[:26]}  {type(e).__name__}", flush=True)
    print()

print("=" * 90)
print(f"需要人工核对的题：{len(suspect)} 道")
print("=" * 90)
for code, q, expect, s, src in suspect:
    hint = "可答题但分数低，可能语料没有" if expect == "可答" else "拒答题但分数高，语料可能有"
    print(f"  {code:<6}{s:<7.3f}{q[:30]:<32}{hint}（top1={src}）")
