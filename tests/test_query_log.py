"""查询日志与后台统计测试（离线，不调 API）。

用 tmp_path 里的临时 SQLite 替换 tools.query_log.DB，不污染真实日志。
覆盖：写入 / 截断 / 概览指标 / 路由与高频问题 / 会话聚合 / 异常吞掉。
"""

from datetime import datetime

import pytest

from tools import query_log


@pytest.fixture
def log_db(tmp_path, monkeypatch):
    db = tmp_path / "query_log.db"
    monkeypatch.setattr(query_log, "DB", db)
    return db


def _seed_two_turns():
    query_log.log_query("问题A", "v1", "search_docs", "答案A", 120, 30, True, "sess1")
    query_log.log_query("问题B", "agent", "query_racket", "答案B", 80, 10, False, "sess2")


def test_log_query_and_recent(log_db):
    _seed_two_turns()

    rows = query_log.recent(10)

    assert [r["question"] for r in rows] == ["问题B", "问题A"]   # 最新的在前
    assert rows[0]["hit"] == 0
    assert rows[1]["hit"] == 1
    assert rows[0]["session_id"] == "sess2"
    assert rows[0]["elapsed_ms"] == 80
    assert rows[0]["tokens"] == 10


def test_log_query_truncates_long_text(log_db):
    query_log.log_query("问" * 600, "v1", "r", "答" * 600, 0, None, True, "s")

    row = query_log.recent(1)[0]
    assert len(row["question"]) == 500
    assert len(row["answer"]) == 500


def test_overview_metrics(log_db):
    _seed_two_turns()

    ov = query_log.overview()

    assert ov["total"] == 2
    assert ov["today"] == 2
    assert ov["sessions"] == 2
    assert ov["miss"] == 1
    assert ov["miss_rate"] == pytest.approx(50.0)
    assert ov["avg_ms"] == 100
    assert ov["agent"] == 1


def test_stats_routes_and_top_questions(log_db):
    _seed_two_turns()
    query_log.log_query("问题A", "v1", "search_docs", "", 10, None, True, "sess3")

    s = query_log.stats()

    assert dict(s["routes"])["search_docs"] == 2
    assert dict(s["routes"])["query_racket"] == 1
    assert dict(s["top_questions"])["问题A"] == 2
    assert s["total"] == 3


def test_sessions_recent_and_by_session(log_db):
    query_log.log_query("第一问", "v1", "search_docs", "答", 10, 1, True, "sess1")
    query_log.log_query("第二问", "v1", "search_docs", "答", 10, 1, False, "sess1")
    query_log.log_query("另一个会话", "agent", "query_racket", "答", 10, 1, True, "sess2")

    sessions = query_log.sessions_recent(10)
    assert len(sessions) == 2

    by_id = {s["session_id"]: s for s in sessions}
    assert by_id["sess1"]["turns"] == 2
    assert by_id["sess1"]["misses"] == 1
    assert by_id["sess1"]["first_q"] == "第一问"

    turns = query_log.by_session("sess1")
    assert [t["question"] for t in turns] == ["第一问", "第二问"]


def test_new_session_id_is_short_hex_and_unique():
    ids = {query_log.new_session_id() for _ in range(50)}

    assert len(ids) == 50
    assert all(len(i) == 8 for i in ids)
    assert all(int(i, 16) >= 0 for i in ids)          # 全是十六进制字符


def test_log_query_swallows_errors(tmp_path, monkeypatch):
    """日志写失败不能影响主流程：DB 指向一个目录，连接必然失败。"""
    monkeypatch.setattr(query_log, "DB", tmp_path)

    assert query_log.log_query("q", "v1", "r") is None


def test_timestamp_is_iso_seconds(log_db):
    query_log.log_query("q", "v1", "r", "a", 1, 1, True, "s")

    ts = query_log.recent(1)[0]["ts"]
    parsed = datetime.fromisoformat(ts)
    assert parsed.year >= 2024
