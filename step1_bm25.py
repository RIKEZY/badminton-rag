"""
第一步：建 BM25 索引，单独测一下。
目标只有一个 —— 看到 BM25 能把含 "Rally" 定义的那块排到前面。

跑法：
    .venv\Scripts\python.exe step1_bm25.py
"""

import json

from rank_bm25 import BM25Okapi

chunks = json.load(open("chunks.json", encoding="utf-8"))
print(f"共 {len(chunks)} 块\n")

# ① 把每块文本变成「词列表」：转小写，按空格切开
#    英文没有分词问题，中文才需要分词器
corpus = [c["text"].lower().split() for c in chunks]

# ② 建索引，把上面那个语料传进去
bm25 = BM25Okapi(corpus)

# ③ 查询也要切成词列表，然后用 get_scores 打分
query = "rally definition".lower().split()
scores = bm25.get_scores(query)

# ④ 按分数从高到低排，取前 5 个「下标」
#    sorted 的 key 是个函数：输入下标 i，返回第 i 块的分数
#    reverse=True 表示从大到小
order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
top5 = order[:5]

print("BM25 top5：")
for rank, idx in enumerate(top5, 1):
    c = chunks[idx]
    print(f"{rank}. 块{idx}  第{c['page']}页  分数 {scores[idx]:.2f}")
    print(f"   {c['text'][:110].replace(chr(10), ' ')}")
    print()
