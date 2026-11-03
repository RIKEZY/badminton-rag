"""新评测集候选：先验证答案块存在，再定题

规则：每道题的期望关键词必须能在语料里找到，否则题目无效。
"""
import json

cs = json.load(open("chunks_v2.json", encoding="utf-8"))

# (题号, 问题, 来源文件, 期望关键词, 考点)
CANDIDATES = [
    (1, "主裁判和发球裁判分别由谁任命？", "bwf_itto.txt",
     "Service Judge and Line Judges are normally appointed", "裁判·职责"),
    (2, "球员在场上行为不当，主裁判可以怎么处理？", "bwf_itto.txt",
     "5.17", "裁判·判罚"),
    (3, "发球裁判主要负责判什么？", "bwf_itto.txt",
     "Instructions to Service Judges", "裁判·发球裁判"),
    (4, "裁判长在赛事中承担什么职责？", "bwf_itto.txt",
     "in overall charge of the tournament", "裁判·裁判长"),
    (5, "世界排名积分在多少周内有效？", "bwf_ranking.txt",
     "52", "赛事·积分周期"),
    (6, "团体赛事的积分怎么计入世界排名？", "bwf_ranking.txt",
     "Team Tournaments", "赛事·团队积分"),
    (7, "裁判要求球员换同色服装时会怎么说？", "bwf_vocabulary.txt",
     "same colour", "术语·裁判用语"),
    (8, "比赛中间歇时，裁判需要做哪些事？", "bwf_itto.txt",
     "interval", "跨文档·裁判操作"),
]

print(f"{'#':<3}{'关键词命中':<10}{'块数':<6}{'考点':<18}问题")
print("-" * 84)

for num, q, src, kw, tag in CANDIDATES:
    hits = [c for c in cs if c["source"] == src and kw.lower() in c["text"].lower()]
    ok = "OK" if hits else "MISS"
    print(f"{num:<3}{ok:<10}{len(hits):<6}{tag:<18}{q}")
    if hits:
        print(f"      ↳ {hits[0]['text'][:110].replace(chr(10), ' ')}")
    else:
        print("      ↳ 语料中未找到，题目需重设")
    print()
