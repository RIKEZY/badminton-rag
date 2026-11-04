"""备份查询日志

用 sqlite3 的 backup API 而不是 cp：服务正在写的时候直接复制文件，
可能拷到只写了一半的页。backup API 是事务一致的。

服务器上由 /etc/cron.d/badminton-log-backup 每天 03:15 调用。
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path

SRC = Path(os.getenv("QUERY_LOG_DB", "/var/lib/badminton-rag/query_log.db"))
DST_DIR = Path(os.getenv("QUERY_LOG_BACKUP_DIR", "/var/backups/badminton-rag"))
KEEP_DAYS = int(os.getenv("QUERY_LOG_BACKUP_KEEP_DAYS", "30"))

if not SRC.exists():
    raise SystemExit(f"日志不存在：{SRC}")

DST_DIR.mkdir(parents=True, exist_ok=True)
dst = DST_DIR / f"query_log-{datetime.now():%Y%m%d}.db"

with sqlite3.connect(SRC) as src, sqlite3.connect(dst) as out:
    src.backup(out)

# 清理超过保留期的备份
cutoff = datetime.now().timestamp() - KEEP_DAYS * 86400
for f in DST_DIR.glob("query_log-*.db"):
    if f.stat().st_mtime < cutoff:
        f.unlink()

n = len(list(DST_DIR.glob("query_log-*.db")))
print(f"已备份 {dst.name}（{dst.stat().st_size} 字节），当前共 {n} 份")
