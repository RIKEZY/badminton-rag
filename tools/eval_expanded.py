"""扩展评测集：分四组，判定方式不同

为什么要分组：
    「答不出」有四种原因，修法完全不同。
    - 正样本答不出 → 检索或生成有问题
    - 负样本答出 → 模型在编（幻觉）
    - 已知缺口答不出 → 正常，记录边界
    混在一起算一个命中率，等于把四种问题平均掉，看不出该修什么。
"""
import os
import re
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

# ── 组 1：正样本（语料有明确答案，答不出就是系统问题）
POSITIVE = [
    ("21 分制下 20 平之后怎么算赢？",
     [("wiki_badminton_zh.txt", 1, "20 平后须领先 2 分取胜")], "规则"),
    ("发球时球拍必须朝下吗？",
     [("wiki_badminton_zh.txt", 1, "拍头应朝向下方")], "规则"),
    ("正手拍和反手拍分别适合什么情况？",
     [("wiki_badminton_zh.txt", 1, "正手拍用于右方")], "技术"),
    ("新手应该选 3U 还是 4U 的球拍？",
     [("gear_rackets.txt", 1, "数字越大，拍子越轻")], "装备"),
    ("羽毛球拍的平衡点怎么影响打法？",
     [("gear_rackets.txt", 1, "平衡点分三类")], "装备"),
    ("司线裁判判错了可以改判吗？",
     [("bwf_itto.txt", 1, "the Umpire shall overrule the decision")], "裁判"),
    ("世界巡回赛分几个级别？",
     [("bwf_gcr.txt", 1, "BWF World Tour (Grade 2)")], "赛事"),
    ("比赛种子怎么排？",
     [("bwf_gcr.txt", 1, "The seeding of the draw at all BWF Sanctioned Tournaments")], "赛事"),
    ("间歇时裁判需要做什么，规则怎么规定的？",
     [("bwf_itto.txt", 1, "The Umpire in consultation with the Referee shall exercise flexibility"),
      ("bwf_itto.txt", 1, "The timing of the interval allowed under Law 16.2.1")], "跨文档"),
    ("球拍尺寸有规定吗？",
     [("wiki_badminton_zh.txt", 1, "总长度不得大于 680 毫米")], "规则"),
    # 以下 4 题原先被误判成「缺口」，实际语料里有答案（见 recheck_gaps.py）
    ("一局结束后什么时候换边？",
     [("bwf_laws_2027.txt", 1, "Players shall change ends"),
      ("badminton_rules.pdf", 5, "Players shall change ends")], "规则"),
    ("裁判出示黄牌是警告还是罚分？",
     [("bwf_itto.txt", 1, "formal warning for misconduct (yellow card)")], "裁判"),
    ("比赛中球员可以要求擦汗或喝水吗？",
     [("bwf_itto.txt", 1, "A quick towel only")], "裁判"),
    ("球落在边线上算出界吗？",
     [("bwf_laws_2027.txt", 1, "lands outside the boundaries of the court")], "规则"),
]

# ── 组 2：负样本（语料确实没有，正确行为是拒答）
NEGATIVE = [
    "2028 年奥运会羽毛球比赛在哪个场馆？",
    "林丹拿过几次世锦赛冠军？",
    "中国国家队现任主教练是谁？",
]

# ── 组 3：已知缺口（用户会问，语料确实没有，只能补数据）
# 注意：判「语料缺失」必须真的搜过原文关键词，不能只看检索分数。
# 这三道题都搜过：net shot 0 处、string tension 0 处、无入门/选拍/双打内容。
GAPS = [
    ("网前搓球的技术要点是什么？", "语料缺失", "net shot 0 处"),
    ("球线磅数越高越好吗？", "语料缺失", "string tension 0 处"),
    ("打球老是打不到球怎么办？", "语料缺失", "无入门级内容"),
    ("拍子太重要不要换一个？", "语料缺失", "无选拍建议"),
    ("双打老是撞拍怎么办？", "语料缺失", "无双打内容"),
]

REFUSE_MARKERS = ("没有", "未收录", "不知道", "无法", "资料中没", "没有提到")


def hit_in(hits, expected):
    for _, c in hits:
        for src, page, kw in expected:
            if c["source"] == src and c["page"] == page and kw in c["text"]:
                return True
    return False


def main():
    print(f"语料 {len(app.chunks)} 块\n")

    # 组 1
    print("=" * 78)
    print(f"组 1 · 正样本（{len(POSITIVE)} 题）—— 答不出就是系统问题")
    print("=" * 78)
    ok = 0
    for q, exp, tag in POSITIVE:
        _, hits = app.retrieve(q, 5)
        h = hit_in(hits, exp)
        ok += h
        top = f"{hits[0][1]['source'][:18]}p{hits[0][1]['page']}"
        print(f"  [{'OK  ' if h else 'MISS'}] {tag:<6}{q[:26]:<28}top1={top}")
    print(f"  → {ok}/{len(POSITIVE)} = {ok / len(POSITIVE) * 100:.0f}%")

    # 组 2
    print("\n" + "=" * 78)
    print(f"组 2 · 负样本（{len(NEGATIVE)} 题）—— 正确行为是拒答")
    print("=" * 78)
    import agent_core
    refused = 0
    for q in NEGATIVE:
        _, ans = agent_core.run(q)
        did = any(m in ans for m in REFUSE_MARKERS)
        refused += did
        print(f"  [{'OK  ' if did else 'FAIL'}] {q[:30]:<32}{ans[:56].replace(chr(10), ' ')}")
    print(f"  → 正确拒答 {refused}/{len(NEGATIVE)}")

    # 组 3
    print("\n" + "=" * 78)
    print(f"组 3 · 已知缺口（{len(GAPS)} 题）—— 记录边界，不判对错")
    print("=" * 78)
    for q, reason, note in GAPS:
        _, hits = app.retrieve(q, 5)
        top_score, top_c = hits[0]
        print(f"  [{reason:<5}] 最高分 {top_score:.3f}  {q[:26]:<28}{note}")

    print("\n" + "=" * 78)
    print("汇总")
    print("=" * 78)
    print(f"  正样本 {ok}/{len(POSITIVE)} · 负样本拒答 {refused}/{len(NEGATIVE)} · "
          f"已知缺口 {len(GAPS)} 题（不计入命中率）")
    print(f"  可判定命中率：{(ok + refused)}/{len(POSITIVE) + len(NEGATIVE)} = "
          f"{(ok + refused) / (len(POSITIVE) + len(NEGATIVE)) * 100:.0f}%")


if __name__ == "__main__":
    main()
