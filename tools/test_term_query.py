"""验证：直接用术语检索，能否命中目标块

如果成立，就可以加一路「术语直查」——绕过 LLM 翻译环节，
用中文术语直接映射成英文词去搜，不依赖改写质量。
"""
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
from hybrid import bm25_search_idx

# (中文术语, 直接用于检索的英文词, 期望命中的块)
CASES = [
    ("换边", "change ends", [18, 460]),
    ("界外", "lands outside the boundaries", [27, 469]),
    ("间歇", "interval", None),
    ("发球区", "service court", None),
    ("违例", "fault", None),
    ("重发", "let", None),
]

print(f"{'中文术语':<10}{'检索词':<34}{'top5 块号':<24}{'命中'}")
print("-" * 90)
for zh, en, expect in CASES:
    hits = bm25_search_idx(app.bm25, app.chunks, en, k=5)
    idxs = [i for _, i in hits]
    mark = ""
    if expect:
        ok = [i for i in expect if i in idxs]
        mark = f"✅ {ok}" if ok else "❌ 未命中"
    print(f"{zh:<10}{en:<34}{str(idxs):<24}{mark}")

print("\n对比：走完整检索链路（含 LLM 改写）")
print("-" * 90)
for q, expect in [("一局结束后什么时候换边？", [18, 460]),
                  ("球落在边线上算出界吗？", [27, 469])]:
    _, hits = app.retrieve(q, 5)
    idxs = [app.chunks.index(c) for _, c in hits]
    ok = [i for i in expect if i in idxs]
    print(f"{q[:22]:<24}top5={idxs}  {'✅ ' + str(ok) if ok else '❌ 未命中'}")
