"""
混合检索：向量 + BM25 + RRF 融合

为什么要有这个文件：
向量看"意思像不像"，BM25 看"词在不在"。两路各有盲区，融合后互补。

为什么用 RRF 而不是把分数加起来：
两路分数不可比。向量是 0~1，BM25 无上界。直接相加等于只用 BM25。
RRF 只看排名，不看分数，所以能把两种尺度对齐。
"""
import json
import re

import jieba
from rank_bm25 import BM25Okapi

from index_builder import embed_query

RRF_K = 20

CJK_RE = re.compile(r"[\u4e00-\u9fa5]")


def tokenize(text: str) -> list[str]:
    """
    中英自适应分词。

    英文按空格切，中文用 jieba。
    为什么不能统一按空格切：中文没有空格，整句会被当成一个 token，
    BM25 的词频统计完全失效——它找不到「发球」这个词，只看到一个长字符串。
    """
    text = text.lower()
    if CJK_RE.search(text):
        return [w for w in jieba.lcut(text) if w.strip()]
    return text.split()


#建bm25索引
def build_bm25(chunks: list[dict]) -> BM25Okapi:
    """建 BM25 索引。语料 = 每块的词列表（中英自适应分词）"""
    corpus = [tokenize(c["text"]) for c in chunks]
    return BM25Okapi(corpus)

#进行向量检索 返回
def vector_search_idx(client, chunks, vecs, query: str, k: int = 5):
    """
    向量检索，返回 [(分数, 下标), ...]

    注意这里返回的是「下标」，不是 chunk 本身。
    因为要和 BM25 的结果对齐——两边都用下标当唯一标识，融合时才不会错。
    """
    q = embed_query(client, query)
    scores = vecs @ q
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [(float(scores[i]), i) for i in order[:k]]

#进行bm25检索 返回
def bm25_search_idx(bm25: BM25Okapi, chunks: list[dict], query: str, k: int = 5):
    """BM25 检索，返回 [(分数, 下标), ...]。查询同样走中英自适应分词"""
    scores = bm25.get_scores(tokenize(query))
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [(float(scores[i]), i) for i in order[:k]]

#进行rrf融合
def rrf_fuse(*hit_lists, top_n: int = 5, k: int = RRF_K):
    """
    RRF 融合，支持任意多路。

    为什么要多路：语料里中英文并存时，单一语言的查询会漏掉另一种语言的块。
        中文原问 → 检索中文块（维基）
        英文改写 → 检索英文块（BWF 规则）
    两路都要，缺一路就漏一半语料。

    输入：任意个 [(分数, 下标), ...]，各自的分数尺度可以完全不同
    输出：[(rrf分数, 下标), ...]，按分数降序取前 top_n

    核心：只比排名不比分数。同一个块在多路里都靠前，累加后自然排最前。
    """
    scores: dict[int, float] = {}
    for hits in hit_lists:
        for rank, (_, idx) in enumerate(hits, 1):
            scores[idx] = scores.get(idx, 0) + 1 / (k + rank)

    order = sorted(scores.keys(), key=lambda i: scores[i], reverse=True)
    return [(scores[i], i) for i in order[:top_n]]


def fuse_by_language(zh_hit_lists, en_hit_lists, top_n: int = 5,
                     candidate_k: int = 10, k: int = RRF_K,
                     term_hit_lists=None):
    """
    两级融合：先语言内部融合，再跨语言融合。

    为什么要两级而不是把所有路平铺：
        平铺时，路数多的一方获得额外投票权。英文侧有「向量 + BM25」两路，
        中文侧只有「向量」一路，英文块天然多拿一次分——不是因为它更相关。
        两级融合让每个语言作为一个整体参与竞争，权重对等。

    term_hit_lists：术语直查的路（中文术语 → 英文术语 → BM25）。
        必须单独成组，不能并进英文侧——术语路通常只有 1-2 路，
        并进英文侧会被 6 路改写稀释掉。实测「球落在边线上」这题，
        术语路本身排第 1，但并进英文侧后 RRF 总分进不了 top5。

    candidate_k：每侧先保留多少候选。必须比 top_n 大，
                 否则跨语言融合时候选池太小，召回广度会打折。
    """
    zh_fused = rrf_fuse(*zh_hit_lists, top_n=candidate_k, k=k)
    en_fused = rrf_fuse(*en_hit_lists, top_n=candidate_k, k=k)
    groups = [zh_fused, en_fused]
    if term_hit_lists:
        groups.append(rrf_fuse(*term_hit_lists, top_n=candidate_k, k=k))
    return rrf_fuse(*groups, top_n=top_n, k=k)


if __name__ == "__main__":
    chunks = json.load(open("chunks.json", encoding="utf-8"))
    bm25 = BM25Okapi(chunks)
    vector_hits = vector_search_idx(chunks)
    bm25_hits = bm25_search_idx(chunks)

