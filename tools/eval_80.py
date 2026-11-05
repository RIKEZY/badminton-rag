"""四组 × 20 题正式评测

每组 17-18 道可答 + 2-3 道拒答。
拒答题的作用只有一个：**检查模型会不会编**（幻觉/乱答/乱编）。

判定方式：
    可答题 —— top1 rerank 分数 >= 0.3 算命中（分数只作代理，低分的会单独列出待查）
    拒答题 —— 调完整 Agent 链路，检查回答里有没有拒答标记
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

REFUSE = ("没有", "未收录", "不知道", "无法", "资料中没", "没有提到", "未提及", "查不到")

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
        ("A16", "世界纪录最快杀球速度是多少？", True),
        ("A17", "羽毛球运动起源于哪个国家？", True),
        ("A18", "奥运会羽毛球有几个单项？", True),
        ("A19", "安赛龙的身高是多少？", False),
        ("A20", "林丹拿过几次世锦赛冠军？", False),
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
        ("B9", "什么是 IRS？", True),
        ("B10", "什么是 GCR？", True),
        ("B11", "什么情况下会用 yellow card？", True),
        ("B12", "发球时球拍要高于手腕吗？", True),
        ("B13", "双打搭档可以连续击球吗？", True),
        ("B14", "比赛中间可以叫暂停吗？", True),
        ("B15", "双打搭档碰到一起算违例吗？", True),
        ("B16", "球擦网过去了算好球吗？", True),
        ("B17", "可以连续击球两次吗？", True),
        ("B18", "界内界外谁说了算？", True),
        ("B19", "双打老是撞拍怎么办？", False),
        ("B20", "打球膝盖疼怎么办？", False),
    ],
    "C 跨文档": [
        ("C1", "间歇时裁判要做什么，规则怎么规定？", True),
        ("C2", "发球违例有哪些，裁判怎么判？", True),
        ("C3", "换球的规定是什么，裁判怎么操作？", True),
        ("C4", "球员行为不当会被怎么处罚？", True),
        ("C5", "裁判可以改判司线的判罚吗？", True),
        ("C6", "赛事分几个级别，各自积分多少？", True),
        ("C7", "世界排名积分怎么算，保留多久？", True),
        ("C8", "种子怎么排，依据是什么？", True),
        ("C9", "球拍尺寸有规定吗，88S PRO 符合吗？", True),
        ("C10", "羽毛球的标准重量和尺寸是多少？", True),
        ("C11", "球拍中管硬度分几档，各适合什么水平？", True),
        ("C12", "场地规格有哪些要求，网柱怎么固定？", True),
        ("C13", "裁判长和主裁的职责怎么分？", True),
        ("C14", "退赛会有什么后果？", True),
        ("C15", "世界排名、种子排位和抽签之间是什么关系？", True),
        ("C16", "双打发球区和单打有什么区别？", True),
        ("C17", "球速测试标准是什么，比赛用球怎么选？", True),
        ("C18", "尤尼克斯和李宁哪个好？", False),
        ("C19", "现在男单世界第一是谁？", False),
        ("C20", "2028 年奥运会羽毛球在哪个场馆？", False),
    ],
    "D 深度细节": [
        ("D3", "同一型号 3U 和 4U 的磅数上限差多少？", True),
        ("D5", "主裁在什么情况下会请裁判长进场？", True),
        ("D7", "裁判的判罚是最终的吗，有没有例外？", True),
        ("D8", "比赛中球坏了怎么处理？", True),
        ("D9", "发球时球拍必须朝下吗？", True),
        ("D10", "过网击球的判定标准是什么？", True),
        ("D11", "触网算不算违例？", True),
        ("D12", "球触天花板怎么判？", True),
        ("D13", "比赛用球的速度怎么测试？", True),
        ("D14", "发球区错误会怎么判？", True),
        ("D15", "反手过渡球怎么打？", True),
        ("D19", "混双站位怎么配合？", True),
        ("D20", "杀球之后怎么快速回中？", True),
        ("D23", "网前搓球的技术要点是什么？", True),
        ("D24", "正手吊球和劈吊有什么区别？", True),
        ("D25", "网前扑球的技术要点是什么？", True),
        ("D21", "体能训练应该怎么安排？", True),
        ("D22", "怎么预防羽毛球运动损伤？", True),
        ("D26", "羽毛球鞋怎么选？", False),
        ("D27", "业余选手多久能到中级水平？", False),
    ],
}

summary = []

for gname, items in GROUPS.items():
    print("=" * 88)
    print(gname)
    print("=" * 88)
    ans = [x for x in items if x[2]]
    ref = [x for x in items if not x[2]]

    ok, low = 0, []
    for code, q, _ in ans:
        _, hits = app.retrieve(q, 5)
        s, c = hits[0]
        if s >= 0.3:
            ok += 1
            print(f"  [OK  ] {code:<5}{s:<7.3f}{q[:30]:<32}{c['source'][:14]}", flush=True)
        else:
            low.append((code, q, s))
            print(f"  [LOW ] {code:<5}{s:<7.3f}{q[:30]:<32}{c['source'][:14]}", flush=True)

    print(f"  → 可答 {ok}/{len(ans)} = {ok / len(ans) * 100:.0f}%")

    import agent_core
    refused = 0
    print(f"\n  拒答题（{len(ref)} 道）—— 检查是否编造：")
    for code, q, _ in ref:
        _, answer = agent_core.run(q)
        did = any(m in answer for m in REFUSE)
        refused += did
        tag = "OK  " if did else "FAIL"
        print(f"  [{tag}] {code:<5}{q[:24]:<26}{answer[:60].replace(chr(10), ' ')}", flush=True)
    print(f"  → 正确拒答 {refused}/{len(ref)}")
    print()

    summary.append((gname, ok, len(ans), refused, len(ref)))

print("=" * 88)
print("汇总")
print("=" * 88)
print(f"  {'组':<14}{'可答命中':<12}{'拒答正确':<12}{'合计'}")
tot_a = tot_an = tot_r = tot_rn = 0
for g, a, an, r, rn in summary:
    print(f"  {g:<14}{f'{a}/{an}':<12}{f'{r}/{rn}':<12}{f'{a + r}/{an + rn}'}")
    tot_a += a; tot_an += an; tot_r += r; tot_rn += rn
print(f"  {'合计':<14}{f'{tot_a}/{tot_an}':<12}{f'{tot_r}/{tot_rn}':<12}{f'{tot_a + tot_r}/{tot_an + tot_rn}'}")
print(f"\n  总命中率：{(tot_a + tot_r) / (tot_an + tot_rn) * 100:.1f}%")
print(f"  可答命中率：{tot_a / tot_an * 100:.1f}%")
print(f"  拒答正确率：{tot_r / tot_rn * 100:.1f}%")
