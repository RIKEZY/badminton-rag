"""对比：精确型号查询，SQL 与向量检索的差异"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("RAG_TAG", "rules")
os.environ.setdefault("RAG_DATA_DIR", str(ROOT / "data_rules_only"))

from dotenv import load_dotenv

load_dotenv()

import app
from tools.equipment_query import search_model, tension_of

QS = [
    ("ASTROX 100ZZ 的 4U 建议磅数是多少？", "100ZZ"),   # 语料里提到过
    ("ASTROX 88S PRO 的 4U 建议磅数是多少？", "88S PRO"),  # 语料里没有
]

for q, model in QS:
    print("=" * 68)
    print(f"问题：{q}")

    # --- 结构化查询 ---
    rows = search_model(model)
    if rows:
        tj = tension_of(model, "4U")[0]
        print(f"  [SQL] 命中 {rows[0]['model']} → 4U 磅数 {tj['range']}")
    else:
        print("  [SQL] 未找到该型号")

    # --- 向量检索 ---
    _, hits = app.retrieve(q, 5)
    gear = [(s, c) for s, c in hits if "gear" in c["source"]]
    print(f"  [向量] top5 里装备相关块：{len(gear)} 个")
    for s, c in hits[:3]:
        print(f"         {s:.4f} [{c.get('doc_type','?')}] {c['text'][:46].replace(chr(10),' ')}")

    # --- 向量检索 + 生成 ---
    answer, _ = app.generate(app.chat_client, q, app.build_context(hits))
    print(f"  [向量+生成] {answer[:150].replace(chr(10),' ')}")
    print()
