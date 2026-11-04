"""查询日志：记录每次提问，供后台查看

设计原则：
    1. 写日志失败不能影响主流程（全部 try/except 吞掉）
    2. 不记 IP，只记会话 ID——能按会话聚合，又不涉及个人身份
    3. 回答截断到 500 字，避免日志表膨胀
"""
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

# 日志属于数据，不属于代码。生产环境用 QUERY_LOG_DB 指到 /var/lib/ 下，
# 这样部署/回滚怎么覆盖代码目录都不会碰到历史记录。
DB = Path(os.getenv("QUERY_LOG_DB") or (Path(__file__).parent / "query_log.db"))

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
    DB.parent.mkdir(parents=True, exist_ok=True)
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


def sessions_recent(limit: int = 30) -> list[dict]:
    """最近若干个会话，带首问、提问数和未命中数——用于看访问流"""
    sql = """
        SELECT session_id,
               MIN(ts)  AS started_at,
               MAX(ts)  AS last_at,
               COUNT(*) AS turns,
               SUM(CASE WHEN hit = 0 THEN 1 ELSE 0 END) AS misses,
               (SELECT question FROM query_log q2
                 WHERE q2.session_id = q1.session_id ORDER BY id LIMIT 1) AS first_q
          FROM query_log q1
         GROUP BY session_id
         ORDER BY last_at DESC
         LIMIT ?
    """
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, (limit,)).fetchall()]


def by_session(session_id: str) -> list[dict]:
    """某个会话的完整追问链"""
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM query_log WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def overview() -> dict:
    """后台概览指标"""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM query_log").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM query_log WHERE ts >= date('now')").fetchone()[0]
        sessions = conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM query_log").fetchone()[0]
        miss = conn.execute("SELECT COUNT(*) FROM query_log WHERE hit = 0").fetchone()[0]
        avg = conn.execute("SELECT AVG(elapsed_ms) FROM query_log").fetchone()[0] or 0
        agent = conn.execute(
            "SELECT COUNT(*) FROM query_log WHERE mode = 'agent'").fetchone()[0]
    return {
        "total": total, "today": today, "sessions": sessions,
        "miss": miss, "miss_rate": (miss / total * 100) if total else 0,
        "avg_ms": int(avg), "agent": agent,
    }


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
