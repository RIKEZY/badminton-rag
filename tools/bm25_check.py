"""BM25 冒烟测试

验证 BM25 能把含 "Rally" 定义的块排到前面。

这里用最朴素的分词（转小写 + 按空格切），只确认索引本身是通的；
生产链路用的是 hybrid.py 里带 jieba 的中英混合分词。

跑法：
    .venv/Scripts/python.exe tools/bm25_check.py
"""

import sys
from pathlib import Path

# 本脚本在 tools/ 下，业务模块在项目根
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

from rank_bm25 import BM25Okapi

from index_builder import CHUNK_CACHE

chunks = json.loads(CHUNK_CACHE.read_text(encoding="utf-8"))
print(f"共 {len(chunks)} 块（{CHUNK_CACHE.name}）\n")

# ① 把每块文本变成「词列表」：转小写，按空格切开
#    英文没有分词问题，中文才需要分词器
corpus = [c["text"].lower().split() for c in chunks]

# ② 建索引
bm25 = BM25Okapi(corpus)

# ③ 查询也要切成词列表，然后用 get_scores 打分
query = "rally definition".lower().split()
scores = bm25.get_scores(query)

# ④ 按分数从高到低排，取前 5
order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

print("BM25 top5：")
for rank, idx in enumerate(order[:5], 1):
    c = chunks[idx]
    print(f"{rank}. 块{idx}  第{c['page']}页  分数 {scores[idx]:.2f}")
    print(f"   {c['text'][:110].replace(chr(10), ' ')}")
    print()
