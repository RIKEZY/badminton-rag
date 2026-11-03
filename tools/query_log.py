"""查询日志：记录每次提问，供后台查看

设计原则：
    1. 写日志失败不能影响主流程（全部 try/except 吞掉）
    2. 不记 IP，只记会话 ID——能按会话聚合，又不涉及个人身份
    3. 回答截断到 500 字，避免日志表膨胀
"""
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB = Path(__file__).parent / "query_log.db"

DDL = """
CREATE TABLE IF NOT EXISTS query_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    session_id TEXT,
    question   TEXT NOT NULL,
    mode       TEXT,
    route      TEXT,
    answer     TEXT,
    elapsed_ms INTEGER,
    tokens     INTEGER,
    hit        INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_ts ON query_log(ts);
"""


def _conn():
    conn = sqlite3.connect(DB, timeout=5)
    conn.executescript(DDL)
    return conn


def log_query(question: str, mode: str, route: str, answer: str = "",
              elapsed_ms: int = 0, tokens: int | None = None,
              hit: bool = True, session_id: str | None = None) -> None:
    """写一条日志。任何异常都吞掉——日志不该拖垮服务。"""
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT INTO query_log (ts, session_id, question, mode, route, answer, "
                "elapsed_ms, tokens, hit) VALUES (?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"),
                 session_id or "-", question[:500], mode, route,
                 (answer or "")[:500], int(elapsed_ms),
                 tokens, 1 if hit else 0),
            )
    except Exception:
        pass


def recent(n: int = 20) -> list[dict]:
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM query_log ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]


def stats() -> dict:
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM query_log").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM query_log WHERE ts >= date('now')"
        ).fetchone()[0]
        sessions = conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM query_log"
        ).fetchone()[0]
        miss = conn.execute("SELECT COUNT(*) FROM query_log WHERE hit=0").fetchone()[0]
        routes = conn.execute(
            "SELECT route, COUNT(*) c FROM query_log GROUP BY route ORDER BY c DESC LIMIT 8"
        ).fetchall()
        top_q = conn.execute(
            "SELECT question, COUNT(*) c FROM query_log GROUP BY question "
            "ORDER BY c DESC LIMIT 8"
        ).fetchall()
    return {
        "total": total, "today": today, "sessions": sessions, "miss": miss,
        "routes": [tuple(r) for r in routes], "top_questions": [tuple(r) for r in top_q],
    }


def new_session_id() -> str:
    return uuid.uuid4().hex[:8]


if __name__ == "__main__":
    s = stats()
    print(f"总提问 {s['total']} 次 | 今日 {s['today']} 次 | 会话 {s['sessions']} 个 | 未命中 {s['miss']} 次")
    if s["routes"]:
        print("\n路由分布：")
        for r, c in s["routes"]:
            print(f"  {r or '-':<34} {c}")
    if s["top_questions"]:
        print("\n高频问题：")
        for q, c in s["top_questions"]:
            print(f"  {c}× {q[:52]}")
    print("\n最近 10 条：")
    for r in recent(10):
        print(f"  {r['ts'][11:]}  [{r['mode']}/{r['route']}]  {r['question'][:44]}")
        print(f"             {r['elapsed_ms']}ms  {r['tokens'] or '-'}t  "
              f"{'命中' if r['hit'] else '未命中'}  → {(r['answer'] or '')[:40]}")
