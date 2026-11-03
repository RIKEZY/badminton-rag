"""v2 评测：老 10 题 + 新 8 题（覆盖裁判 / 赛事 / 术语 / 跨文档）"""
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

# 新题：期望关键词都收敛到 1–2 块，避免「同章节任何块都算命中」
EVAL_V2 = [
    ("主裁判和发球裁判分别由谁任命？",
     [("bwf_itto.txt", 1, "Service Judge and Line Judges are normally appointed")], "裁判·任命"),
    ("球员在场上行为不当，主裁判可以怎么处理？",
     [("bwf_itto.txt", 1, "honourable and in a sportsmanlike")], "裁判·判罚"),
    ("发球裁判坐在哪个位置，主要负责判什么？",
     [("bwf_itto.txt", 1, "sit on a low chair")], "裁判·发球裁判"),
    ("裁判长在赛事中承担什么职责？",
     [("bwf_itto.txt", 1, "in overall charge of the tournament")], "裁判·裁判长"),
    ("世界排名积分在多少周内有效？",
     [("bwf_ranking.txt", 1, "52-week")], "赛事·积分周期"),
    ("团体赛事的积分怎么计入世界排名？",
     [("bwf_ranking.txt", 1, "Team Tournaments")], "赛事·团队积分"),
    ("裁判要求球员换同色服装时会怎么说？",
     [("bwf_vocabulary.txt", 1, "same colour"),
      ("bwf_itto.txt", 1, "same colour")], "术语·裁判用语"),
    ("裁判在什么情况下会换球，具体怎么操作？",
     [("bwf_itto.txt", 1, "Change of Shuttle")], "跨文档·换球"),
]


def is_hit(hits, expected):
    for _, c in hits:
        for src, page, kw in expected:
            if c["source"] == src and c["page"] == page and kw in c["text"]:
                return True
    return False


def run_group(name, cases):
    ok = 0
    print(f"\n===== {name}（{len(cases)} 题）=====")
    for i, item in enumerate(cases, 1):
        q, expected = item[0], item[1]
        tag = item[2] if len(item) > 2 else ""
        _, hits = app.retrieve(q, 5)
        hit = is_hit(hits, expected)
        ok += hit
        mark = "OK  " if hit else "MISS"
        top = f"{hits[0][1]['source'][:16]} p{hits[0][1]['page']}"
        print(f"[{mark}] {i:<2}{tag:<14}{q[:30]:<32}top1={top}")
    print(f"→ {name} Recall@5: {ok}/{len(cases)}")
    return ok


if __name__ == "__main__":
    print(f"语料 {len(app.chunks)} 块")
    a = run_group("老题（规则/技术/装备）", [(q, e) for q, e in EVAL_SET])
    b = run_group("新题（裁判/赛事/术语/跨文档）", EVAL_V2)
    total = len(EVAL_SET) + len(EVAL_V2)
    print(f"\n合计 {a + b}/{total} = {(a + b) / total * 100:.0f}%")
