"""把 9 道拒答题完整跑一遍，抓模型原始回答

拒答题是评测里唯一能测幻觉的一组：语料里没有答案，正确行为是承认不知道。
这个脚本把每题的路由决策、工具调用、完整回答都打出来，方便人工判断
「真拒答」还是「用不相关内容硬答」。
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

import agent_core

REFUSE = ("没有", "未收录", "不知道", "无法", "资料中没", "没有提到", "未提及", "查不到")

QUESTIONS = [
    ("A19", "安赛龙的身高是多少？"),
    ("A20", "林丹拿过几次世锦赛冠军？"),
    ("B19", "双打老是撞拍怎么办？"),
    ("B20", "打球膝盖疼怎么办？"),
    ("C18", "尤尼克斯和李宁哪个好？"),
    ("C19", "现在男单世界第一是谁？"),
    ("C20", "2028 年奥运会羽毛球在哪个场馆？"),
    ("D19", "混双站位怎么配合？"),
    ("D20", "杀球之后怎么快速回中？"),
]

results = []
for code, q in QUESTIONS:
    steps, answer = agent_core.run(q)
    did_refuse = any(m in answer for m in REFUSE)
    results.append({
        "code": code,
        "question": q,
        "refused": did_refuse,
        "steps": [{"action": s["action"], "args": s.get("args")} for s in steps],
        "answer": answer,
    })
    print(f"[{code}] {q}")
    print(f"  判定：{'✅ 正确拒答' if did_refuse else '❌ 幻觉（未拒答）'}")
    print(f"  步骤：{[s['action'] for s in steps]}")
    print(f"  回答：{answer}")
    print()

out = ROOT / "tools" / "refuse_answers.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
ok = sum(1 for r in results if r["refused"])
print(f"正确拒答 {ok}/{len(results)}，完整结果已存 {out.name}")
