"""切块逻辑测试（离线，不调任何 API）。

覆盖：
    - 从原始语料重新切块，块数必须与缓存一致，且逐块文本相同
    - index_builder 在 conftest 固定的环境变量下加载的确实是 v2 语料
    - 条款切分 / 层级前缀 / 兄弟块合并 / 段落回退
    - 缓存块里没有 BWF 页眉（Page X of Y），带条款的块都有层级前缀
"""

import re
from pathlib import Path

import pytest

from chunker import (add_prefix, chunk_document, guess_doc_type, merge_siblings,
                     split_by_paragraph, split_page_by_clause)
from document_loader import load_documents, strip_header

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data_rules_only"
MIN_CHUNK_COUNT = 800
HEADER_RE = re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE)


# ---------------------------------------------------------------- 端到端

def test_source_pipeline_matches_cache(cached_chunks):
    """data_rules_only 重新走一遍 load_documents → chunk_document，必须与缓存一致。"""
    if not DATA_DIR.exists():
        pytest.skip("缺少 data_rules_only 目录")

    docs = load_documents()
    assert docs, "语料目录里没有读到任何文档"

    by_source: dict[str, list[tuple[int, str]]] = {}
    for doc in docs:
        by_source.setdefault(doc["source"], []).append((doc["page"], doc["text"]))

    built = []
    for source, pages in by_source.items():
        built.extend(chunk_document(pages, source))

    assert len(built) >= MIN_CHUNK_COUNT, f"块数异常偏少：{len(built)}"
    # 一致性比具体数字更重要：重新切的块数必须和缓存相同
    assert len(built) == len(cached_chunks)
    # 切块是确定性的：重新切的文本序列应与缓存完全一致
    assert [c["text"] for c in built] == [c["text"] for c in cached_chunks]


def test_index_builder_loads_v2_cache_not_legacy_rules():
    """已知陷阱回归：index_builder.TAG 必须是 v2，不能退回旧的 all/rules。"""
    import index_builder

    assert index_builder.TAG == "v2"
    assert index_builder.CHUNK_CACHE.name == "chunks_v2.json"
    assert len(index_builder.build_chunks()) >= MIN_CHUNK_COUNT


# ---------------------------------------------------------------- 条款切分

def test_split_page_by_clause_structure():
    page = (
        "9. SERVICE\n"
        "\n"
        "9.1. Definition\n"
        "9.1.1. Service is the action of putting the shuttle into play.\n"
        "9.1.2. Both feet must remain in contact with the floor.\n"
    )
    chunks = split_page_by_clause(page, 6, "badminton_rules.pdf")

    assert [c["clause"] for c in chunks] == ["9.1", "9.1.1", "9.1.2"]
    assert all(c["chapter"] == "9. SERVICE" for c in chunks)
    assert all(c["page"] == 6 and c["source"] == "badminton_rules.pdf" for c in chunks)
    # 条款行本身要留在块里
    assert chunks[1]["text"].startswith("9.1.1. Service is")


def test_add_prefix_contains_chapter_and_clause():
    chunk = add_prefix({
        "source": "badminton_rules.pdf", "page": 6,
        "clause": "9.1.1", "chapter": "9. SERVICE",
        "text": "9.1.1. Service is the action of putting the shuttle into play.",
    })

    assert chunk["prefix"] == "[Law 9. SERVICE > 9.1.1] "
    assert chunk["text"].startswith("[Law 9. SERVICE > 9.1.1] 9.1.1. Service is")
    # 原始正文不能被改写，只能加前缀
    assert chunk["text"].endswith("putting the shuttle into play.")


def test_add_prefix_skips_definitions_marker():
    chunk = add_prefix({
        "source": "badminton_rules.pdf", "page": 1,
        "clause": "DEFINITIONS", "chapter": "",
        "text": "Rally: A sequence of exchanges.",
    })
    assert chunk["prefix"] == ""
    assert chunk["text"] == "Rally: A sequence of exchanges."


def test_definitions_are_not_merged():
    def mk(text):
        return {"source": "x", "page": 1, "clause": "DEFINITIONS",
                "chapter": "", "text": text}

    chunks = [mk("Rally: A sequence of exchanges."),
              mk("Service: The action of putting the shuttle into play.")]
    assert len(merge_siblings(chunks)) == 2


# ---------------------------------------------------------------- 章标题跨页继承

def test_split_page_inherits_chapter_across_page_break():
    """章标题只在章首页出现：翻页后的 6.6 必须仍带 [Law 6. SERVICE]。"""
    state: dict = {}
    page36 = split_page_by_clause(
        "6. SERVICE\n"
        "6.4. The server shall not serve until the receiver is ready.\n"
        "6.5. Once the players are ready, the server shall not delay delivery.\n",
        36, "itto.pdf", state)
    page37 = split_page_by_clause(
        "6.6. The server shall not serve before the receiver is ready.\n"
        "6.7. The receiver shall not move before the service is delivered.\n",
        37, "itto.pdf", state)

    assert [c["chapter"] for c in page36 + page37] == ["6. SERVICE"] * 4
    prefixed = add_prefix(page37[0])
    assert prefixed["prefix"] == "[Law 6. SERVICE > 6.6] "
    assert prefixed["text"].startswith("[Law 6. SERVICE > 6.6] 6.6. The server")


def test_split_page_switches_to_new_chapter_on_new_header():
    """下一页出现新章标题时，后续块切到新章，不能继续沿用旧章名。"""
    state: dict = {}
    split_page_by_clause("6. SERVICE\n6.5. A delivery of service.\n", 36, "itto.pdf", state)
    page37 = split_page_by_clause(
        "6.6. The server shall not serve before the receiver is ready.\n"
        "7. SCORING SYSTEM\n"
        "7.1. A match shall consist of the best of three games.\n",
        37, "itto.pdf", state)

    assert [c["chapter"] for c in page37] == ["6. SERVICE", "7. SCORING SYSTEM"]
    assert [c["clause"] for c in page37] == ["6.6", "7.1"]


def test_chapter_inheritance_does_not_leak_between_sources():
    """两个文件各自调用 chunk_document，章状态不能串。"""
    with_chapter = chunk_document(
        [(1, "6. SERVICE\n6.1. The service shall be delivered from the service court.\n")],
        "itto.pdf")
    without_chapter = chunk_document(
        [(1, "6.1. A tournament entry shall be submitted before the deadline.\n")],
        "bwf_gcr.txt")

    assert with_chapter[0]["chapter"] == "6. SERVICE"
    assert all(c["chapter"] == "" for c in without_chapter)
    assert all("Law" not in c["prefix"] for c in without_chapter)


# ---------------------------------------------------------------- 兄弟合并

def _mk_chunk(clause: str, text: str, page: int = 6) -> dict:
    return {"source": "badminton_rules.pdf", "page": page,
            "clause": clause, "chapter": "9. SERVICE", "text": text}


def test_merge_siblings_merges_same_parent():
    chunks = [
        _mk_chunk("9.1", "Definition."),
        _mk_chunk("9.1.1", "Service is the action."),
        _mk_chunk("9.1.2", "Both feet must stay on the floor."),
    ]
    merged = merge_siblings(chunks, max_len=1200)

    assert len(merged) == 1
    assert merged[0]["clause"] == "9.1"          # 保留父级编号
    for piece in ("Definition.", "Service is the action.", "Both feet"):
        assert piece in merged[0]["text"]


def test_merge_siblings_respects_max_len():
    chunks = [_mk_chunk("9.1", "a" * 700), _mk_chunk("9.1.1", "b" * 700)]
    assert len(merge_siblings(chunks, max_len=1200)) == 2


def test_merge_siblings_does_not_merge_different_parents():
    chunks = [_mk_chunk("9.1.1", "a" * 50), _mk_chunk("9.2.1", "b" * 50)]
    assert len(merge_siblings(chunks, max_len=1200)) == 2


# ---------------------------------------------------------------- 引言块归属
# 回归 P0-1：`same_parent = prev_parent == curr_parent or not prev_parent`
# 对引言块（clause=""）永远成立，且 `len("".split(".")) == 1` 让后续条款
# 永远不满足“更短”，于是引言会一路吞掉后面所有章节的条款，直到 max_len。

def test_merge_siblings_intro_stops_at_parent_boundary():
    """引言块只能吸收同一父级的条款，不能跨父级吞并。"""
    chunks = [
        _mk_chunk("", "It shall be a let, if:"),
        _mk_chunk("14.2.1", "14.2.1. the server serves before the receiver is ready;"),
        _mk_chunk("14.2.2", "14.2.2. at the moment of service the receiver is not ready;"),
        _mk_chunk("14.3.1", "14.3.1. an unforeseen situation has occurred."),
    ]
    merged = merge_siblings(chunks, max_len=1200)

    assert len(merged) == 2
    # 引言块吸收第一个条款时必须写入该条款编号，否则父级比较永远无效
    assert merged[0]["clause"] == "14.2.1"
    assert "14.2.2" in merged[0]["text"]
    assert "14.3.1" not in merged[0]["text"]
    assert merged[1]["clause"] == "14.3.1"


def test_merge_siblings_intro_does_not_cross_new_chapter():
    """上一页/上一章的引言不能吞掉新章节的条款（即使新章节父级数字不同）。"""
    chunks = [
        {"source": "itto.pdf", "page": 22, "clause": "", "chapter": "",
         "text": "...breaches the Rules and Regulations of BWF (or the CC)."},
        {"source": "itto.pdf", "page": 22, "clause": "4.1",
         "chapter": "4. GENERAL ADVICE ON REFEREES",
         "text": "4.1. The Role of the Referee and Relations to Other Stakeholders"},
    ]
    merged = merge_siblings(chunks, max_len=1200)

    assert len(merged) == 2
    assert merged[0]["clause"] == ""
    assert "4.1." not in merged[0]["text"]


def test_merge_siblings_allows_page_break_within_same_parent():
    """回归保护：Law 14 的 14.2.x 跨页，页码变了但父级相同，仍应合并。

    页码切换后 split_page_by_clause 的章标题会重置成空字符串，
    所以不能要求 chapter 严格相等，否则会拆散 let 的条件列表。
    """
    chunks = [
        _mk_chunk("14.2.1", "14.2.1. a", page=9),
        {"source": "badminton_rules.pdf", "page": 10, "clause": "14.2.7",
         "chapter": "", "text": "14.2.7. any unforeseen situation."},
    ]
    merged = merge_siblings(chunks, max_len=1200)

    assert len(merged) == 1
    assert "14.2.7" in merged[0]["text"]


def test_merge_siblings_keeps_first_clause_label_for_deep_siblings():
    """块的编号必须对应正文第一个条款，不能被后面更短的兄弟条款覆盖。

    原规则 `len(c) < len(prev)` 会把 9.1.4.1 + 9.1.5 的块标成 9.1.5，
    正文却从 9.1.4.1 开始，引用编号因此错位。
    """
    chunks = [
        _mk_chunk("9.1.4.1", "9.1.4.1. In Wheelchair Badminton ..."),
        _mk_chunk("9.1.5", "9.1.5. the movement of the server's racket ..."),
    ]
    merged = merge_siblings(chunks, max_len=1200)

    assert len(merged) == 1
    assert merged[0]["clause"] == "9.1.4.1"
    assert merged[0]["text"].startswith("9.1.4.1.")


# ---------------------------------------------------------------- 段落回退

def test_split_by_paragraph_merges_short_heading():
    heading = "一、YONEX ASTROX 100ZZ"           # 短标题，< 50 字
    body = "拍框材质为高弹性碳素，建议磅数 4U 20-28。" * 5
    chunks = split_by_paragraph([(1, f"{heading}\n\n{body}")], "gear_rackets.txt")

    assert len(chunks) == 1
    assert heading in chunks[0]["text"]
    assert "建议磅数" in chunks[0]["text"]


def test_split_by_paragraph_splits_oversized_paragraph():
    chunks = split_by_paragraph([(1, "x" * 2000)], "wiki_badminton_zh.txt", max_len=800)

    assert len(chunks) >= 3
    assert all(len(c["text"]) <= 800 for c in chunks)
    # 拼回去应覆盖原文（允许切分点 strip 带来的空白差异）
    assert sum(len(c["text"]) for c in chunks) >= 1900


# ---------------------------------------------------------------- 文档类型

@pytest.mark.parametrize("source,expected", [
    ("bwf_itto.txt", "裁判"),
    ("bwf_ranking.txt", "赛事"),
    ("bwf_gcr.txt", "赛事"),
    ("bwf_facilities.txt", "场馆"),
    ("badminton_rules.pdf", "规则"),
    ("bwf_laws_2027.txt", "规则"),
    ("bwf_vocabulary.txt", "规则"),
    ("tech_high_clear.txt", "技术"),
    ("gear_rackets.txt", "装备"),
    ("wiki_badminton_zh.txt", "百科"),
    ("unknown_source.txt", "其他"),
])
def test_guess_doc_type(source, expected):
    assert guess_doc_type(source) == expected


# ---------------------------------------------------------------- 缓存质量

def test_strip_header_removes_bwf_page_line():
    raw = ("BWF Statutes, Section 4.1: Law of Badminton          Page 5 of 14\n"
           "9.1.1. Service is the action of putting the shuttle into play.")
    clean = strip_header(raw)

    assert "Page 5 of 14" not in clean
    assert "BWF Statutes" not in clean
    assert clean == "9.1.1. Service is the action of putting the shuttle into play."


def test_cached_chunks_have_no_page_header(cached_chunks):
    offenders = [c for c in cached_chunks if HEADER_RE.search(c["text"])]
    assert offenders == [], f"有 {len(offenders)} 块残留 BWF 页眉（Page X of Y）"


def test_cached_chunks_structure_and_prefix(cached_chunks):
    assert len(cached_chunks) >= MIN_CHUNK_COUNT

    allowed_types = {"规则", "技术", "装备", "百科", "裁判", "赛事", "场馆", "其他"}
    assert {c.get("doc_type") for c in cached_chunks} <= allowed_types

    for c in cached_chunks:
        assert c["text"].strip(), "存在空块"
        assert c["source"], "存在没有 source 的块"
        assert isinstance(c["page"], int) and c["page"] >= 1

    # 带条款号的块必须有层级前缀，且正文以该前缀开头
    clause_chunks = [c for c in cached_chunks
                     if c["clause"] and c["clause"] != "DEFINITIONS"]
    assert clause_chunks, "没有任何带条款号的块，切块逻辑可能退化"
    for c in clause_chunks:
        assert c["prefix"].startswith("["), f"块 {c['clause']} 缺少层级前缀"
        assert c["clause"] in c["prefix"]
        assert c["text"].startswith(c["prefix"])

    # 约六成块有条款前缀（技术/百科类没有）；给个下界，避免断言过死
    assert sum(1 for c in cached_chunks if c.get("prefix")) >= 500
    # 来源数同样不硬编码：语料会继续加。改成和语料目录里的文件数对齐——
    # 少一个来源说明某个文件没被读到，这是真问题；多来源是正常的扩充。
    n_sources = len({c["source"] for c in cached_chunks})
    n_files = len([f for f in DATA_DIR.iterdir()
                   if f.suffix.lower() in (".pdf", ".txt", ".md")])
    assert n_sources >= n_files, f"来源数 {n_sources} 少于语料文件数 {n_files}，有文件没被读到"
