"""BM25 检索与 RRF 融合测试（离线，不调任何 API）。

覆盖：
    - 中英自适应分词（中文走 jieba，英文按空格）
    - BM25 能在 649 块语料里命中英文规则块 / 中文技术块
    - RRF 只看排名不看分数尺度
    - 两级融合（语言内部 → 跨语言）让两种语言权重对等
"""

import pytest

from hybrid import (bm25_search_idx, fuse_by_language, rrf_fuse, tokenize)


# ---------------------------------------------------------------- 分词

def test_tokenize_chinese_uses_jieba():
    tokens = tokenize("发球裁判的职责")
    assert "发球" in tokens
    assert "裁判" in tokens
    # 整句不能变成一个 token
    assert "发球裁判的职责" not in tokens


def test_tokenize_english_lowercases_and_splits_on_space():
    assert tokenize("Service Judge Appointment") == ["service", "judge", "appointment"]


def test_tokenize_mixed_text_does_not_crash():
    tokens = tokenize("BWF 发球规则 service fault")
    assert tokens
    assert all(t.strip() for t in tokens)


# ---------------------------------------------------------------- BM25

def test_bm25_index_covers_whole_corpus(bm25_index, cached_chunks):
    assert bm25_index.corpus_size == len(cached_chunks)


def test_bm25_english_query_hits_itto(bm25_index, cached_chunks):
    hits = bm25_search_idx(bm25_index, cached_chunks, "Service Judge appointed", k=5)

    assert hits, "BM25 没有返回任何结果"
    assert hits[0][0] > 0
    top = cached_chunks[hits[0][1]]
    assert top["source"] == "bwf_itto.txt"
    assert "Service Judge" in top["text"]
    # 分数必须降序
    scores = [s for s, _ in hits]
    assert scores == sorted(scores, reverse=True)


def test_bm25_chinese_query_hits_tech_doc(bm25_index, cached_chunks):
    hits = bm25_search_idx(bm25_index, cached_chunks, "反手高远球 击球点", k=5)

    assert hits
    top_texts = [cached_chunks[i]["text"] for _, i in hits]
    assert any("反手高远球" in t for t in top_texts)
    assert all(cached_chunks[i]["source"] == "tech_high_clear.txt" for _, i in hits)


def test_bm25_returns_at_most_k_and_valid_indices(bm25_index, cached_chunks):
    hits = bm25_search_idx(bm25_index, cached_chunks, "interval", k=3)

    assert len(hits) <= 3
    assert all(0 <= i < len(cached_chunks) for _, i in hits)


# ---------------------------------------------------------------- RRF

def test_rrf_prefers_document_appearing_in_both_lists():
    fused = rrf_fuse(
        [(0.9, 1), (0.8, 2)],
        [(0.5, 2), (0.4, 3)],
        top_n=3,
    )

    # 2 在两路里分别排第 2、第 1，累加后应排第一
    assert fused[0][1] == 2
    assert [i for _, i in fused] == [2, 1, 3]
    scores = [s for s, _ in fused]
    assert scores == sorted(scores, reverse=True)


def test_rrf_uses_rank_only_not_raw_scores():
    """两路分数量级差 1000 倍，只要排名一样，融合结果必须一样。"""
    a = rrf_fuse([(999.0, 0), (1.0, 1)], [(0.001, 0)])
    b = rrf_fuse([(0.9, 0), (0.1, 1)], [(0.0001, 0)])

    assert [i for _, i in a] == [i for _, i in b] == [0, 1]
    assert [s for s, _ in a] == pytest.approx([s for s, _ in b])


def test_rrf_truncates_to_top_n():
    fused = rrf_fuse([(1, 0), (1, 1), (1, 2), (1, 3)], top_n=2)
    assert len(fused) == 2
    assert [i for _, i in fused] == [0, 1]


def test_rrf_empty_input():
    assert rrf_fuse() == []
    assert rrf_fuse([], []) == []


def test_fuse_by_language_gives_each_language_equal_weight():
    """中文侧只有 1 路、英文侧 3 路时，也不能让英文块天然多拿票。"""
    zh = [[(1.0, 0), (0.9, 1)]]
    en = [[(1.0, 1), (0.9, 2)]]

    fused = fuse_by_language(zh, en, top_n=3, candidate_k=2)

    # 块 1 在中文侧排第 2、英文侧排第 1，跨语言融合后应第一
    assert fused[0][1] == 1
    assert [i for _, i in fused] == [1, 0, 2]
