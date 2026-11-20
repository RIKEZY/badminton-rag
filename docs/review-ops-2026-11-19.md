
─── tools/query_log.py:35-39 ───
[bug · medium] `_conn()` returns a raw connection, and every caller wraps it in `with _conn() as
conn:` — but for `sqlite3.Connection` the context manager only commits/rolls back, it never calls
`close()`. So no connection is ever closed deterministically; it stays open until refcount/GC
reclaims it, keeping file descriptors (and -wal/-shm files) around and risking `database is locked`
on Windows or when many requests pile up. Also note `executescript(DDL)` runs on every call, taking
a write lock each time and adding overhead on a hot path. Suggest turning `_conn` into a context
manager that guarantees `close()` (and only builds the schema once).

+ from contextlib import contextmanager
+ 
+ 
+ @contextmanager
  def _conn():
      DB.parent.mkdir(parents=True, exist_ok=True)
      conn = sqlite3.connect(DB, timeout=5)
+     try:
-     conn.executescript(DDL)
+         conn.executescript(DDL)
-     return conn
+         yield conn
+         conn.commit()
+     finally:
+         conn.close()


─── tools/query_log.py:72-74 ───
[bug · medium] Time-zone mismatch: `ts` is written with `datetime.now().isoformat()` (local time),
while `date('now')` in SQLite is the **UTC** date. In any timezone ahead of UTC (e.g. UTC+8),
between 00:00 and the UTC rollover the comparison still matches yesterday's local records, so the
"today" count is inflated (and behind UTC it under-counts). `overview()` has the same query. Compare
on the local date boundary, e.g. `WHERE ts >= ?` with `datetime.now().strftime('%Y-%m-%d')` passed
in, or store/compare UTC consistently.

          today = conn.execute(
-             "SELECT COUNT(*) FROM query_log WHERE ts >= date('now')"
+             "SELECT COUNT(*) FROM query_log WHERE ts >= ?",
+             (datetime.now().strftime("%Y-%m-%d"),),
          ).fetchone()[0]


─── tools/query_log.py:93-93 ───
[bug · medium] Only 8 hex chars (32 bits) of a UUID are kept, which is not enough entropy for a
session identifier: collisions become likely at scale (birthday bound ~ a few tens of thousands of
sessions), and a collision silently merges two different users' turn chains in
`sessions_recent()`/`by_session()`. It is also trivially guessable if the id is ever used to look up
a session. Keep at least 16 hex chars (64 bits) or the full `uuid4().hex`.

-     return uuid.uuid4().hex[:8]
+     return uuid.uuid4().hex[:16]


─── tools/query_log.py:31-31 ───
[performance · low] Only `ts` is indexed, yet the hot read paths all filter/group on `session_id`:
`by_session()` does `WHERE session_id = ?`, `sessions_recent()` does `GROUP BY session_id` plus a
correlated subquery per session, and both `stats()`/`overview()` run `COUNT(DISTINCT session_id)`.
All of these degrade to full table scans as the log grows. Adding an index on `session_id` (or
`(session_id, id)` so the `ORDER BY id` branch is covered) would keep the admin page responsive.

  CREATE INDEX IF NOT EXISTS idx_ts ON query_log(ts);
+ CREATE INDEX IF NOT EXISTS idx_session ON query_log(session_id, id);


─── tools/query_log.py:56-57 ───
[maintainability · low] Catching `Exception` and discarding it with a bare `pass` means any
persistent failure (schema mismatch, `database is locked`, disk full, or a `TypeError` from e.g.
`int(None)`) silently drops every log entry with no trace at all, making such outages undiagnosable.
Since failing to log must not break the request, keep the swallow but emit it at debug level (and
ideally rate-limit) so the problem is observable.

      except Exception:
-         pass
+         logger.debug("log_query failed", exc_info=True)


─── run_eval.py:103-103 ───
[bug · high] `lstrip("0123456789.-、) ")` strips any leading digits, so legitimate English rewrites
that start with a number are corrupted: `60 seconds interval` -> `seconds interval`, `4U racket
tension` -> `U racket tension`, `4.74 grams` -> `grams`. Since EVAL_SET deliberately contains
numeric questions (#2 `60 秒`, #8 `4U`, #10 `4.74`), this silently degrades the retrieval queries and
skews Recall@5. Only strip an actual numbering/bullet prefix instead (add `import re` at the top).

-         ln = ln.strip().lstrip("0123456789.-、) ").strip()
+         # 只去掉行首编号/项目符号，不能吞掉查询内容开头的数字（60 seconds / 4U / 4.74）
+         ln = re.sub(r"^\s*(?:\d+[.)、]\s*|[-•*]\s*)", "", ln).strip()


─── run_eval.py:200-202 ───
[bug · medium] `hit_count += hit` and `details.append((question, hit))` run before the
printing/`generate()` calls, but the surrounding `except` unconditionally appends `(question,
False)`. If `generate()` or later printing raises, the same question is recorded twice (one hit, one
miss): Recall counts it as a hit while the "未命中的题" list reports it as missed. Only append the
failure entry when the question has not already been recorded.

          except Exception as e:
              print(f"  ⚠️ 出错: {type(e).__name__}: {e}")
+             # 命中已在 try 里登记过，避免重复追加 False 导致 Recall 与「未命中」列表不一致
+             if not any(q == question for q, _ in details):
-             details.append((question, False))
+                 details.append((question, False))


─── run_eval.py:205-206 ───
[bug · medium] If `RAG_EVAL_LIMIT=0` (or the env value is invalid such that the slice is empty),
`subset` is empty and the loop is skipped, so `hit_count / len(subset)` raises `ZeroDivisionError`
before the summary is printed. Guard the empty-subset case before computing the ratio.

+     if not subset:
+         print("没有可评测的题目（请检查 RAG_EVAL_LIMIT）")
+         return
      print(f"Recall@{TOP_K}: {hit_count}/{len(subset)}"
            f"  ({hit_count / len(subset) * 100:.0f}%)")


─── run_eval.py:23-24 ───
[maintainability · low] `rrf_fuse` is imported but never called in this file (all fusion goes
through `fuse_by_language`), leaving dead code that obscures the actual retrieval path. Remove it
from the import.

  from hybrid import (bm25_search_idx, build_bm25, fuse_by_language,
-                     rrf_fuse, vector_search_idx)
+                     vector_search_idx)


─── run_eval.py:77-80 ───
[maintainability · low] `SYSTEM_PROMPT` is defined but never referenced. `generate()` in
`answer_generator.py` hard-codes its own system prompt, so this constant is dead and misleading—a
reader would assume it affects the generated answers. Delete it or pass it into the generation path
explicitly.



─── run_eval.py:145-148 ───
[bug · low] `CHAT_MODEL` defaults to `""` and `CHAT_BASE_URL` defaults to `""` (unlike
`answer_generator.py`, which defaults to `deepseek-chat` / `https://api.deepseek.com` and validates
the API keys). With a missing/blank env var the client is constructed with an empty model/base_url,
and because per-question exceptions are caught and only printed as warnings, the script silently
reports `Recall@5: 0/10` instead of failing loudly. Validate the chat config up front (or reuse the
defaults from `answer_generator.py`) so misconfiguration is obvious.

+     if not CHAT_MODEL:
+         raise SystemExit("缺少 DEEPSEEK_MODEL")
      chat_client = OpenAI(
          api_key=os.getenv("DEEPSEEK_API_KEY", "").strip(),
          base_url=CHAT_BASE_URL,
      )


─── scripts/deploy.sh:65-69 ───
[bug · high] `equipment.db` is copied with `scp` directly onto the live SQLite file while
`badminton-rag`/`badminton-admin` are still running (restart only happens in step 3). A running
SQLite process may be holding the file/page cache, and the copy is not atomic — a reader during the
copy can see a truncated/partial file ("database disk image is malformed", stale locks). Safer
options: (a) upload to `tools/equipment.db.new` and `mv` it into place after `systemctl stop` on
both services (rename is atomic on the same FS), or (b) back up the remote DB with `sqlite3 <db>
".backup <tmp>"` and swap it in. At minimum, the DB should not be overwritten in-place by scp while
the service is live.



─── scripts/deploy.sh:249-250 ───
[bug · high] Rollback restarts only `${SERVICE_NAME}`. The admin service (`badminton-admin`) also
has its files reverted by the tar extraction but keeps running the pre-rollback code (and may fail
after its on-disk files changed), so the post-rollback `/ops/` probe can fail even though rollback
was successful. Restart both services, symmetric with `restart_script`.

  tar -xzf "${bak}" -C "${REMOTE_DIR}"
- ${SUDO} systemctl restart ${SERVICE_NAME}
+ ${SUDO} systemctl restart ${SERVICE_NAME} ${ADMIN_SERVICE_NAME}


─── scripts/deploy.sh:247-249 ───
[bug · high] `rollback_script` never refreshes `/tmp/badminton-rag-restart.ts` before restarting.
After rollback, `health_check` computes `SINCE_ARG` from the timestamp written before the *failed*
restart, so `journalctl` replays the errors produced by the bad deployment and `check_log` fails
again. `do_rollback` then reports "回滚后健康检查仍未通过，需要人工介入" and exits 2 even though the rollback actually
worked. Write a fresh timestamp here, exactly as `restart_script` does.

  cd "${REMOTE_DIR}"
  echo "   解包备份: ${bak}"
  tar -xzf "${bak}" -C "${REMOTE_DIR}"
+ date +%s > /tmp/badminton-rag-restart.ts


─── scripts/deploy.sh:356-357 ───
[bug · medium] `BACKUP_PATH` is resolved as "the newest tarball" after the backup step rather than
the exact file this run produced. If another deploy (or any concurrent backup) runs at the same
moment, `ls -1t | head -n 1` can return the other run's archive, and a later rollback would restore
a version that was never deployed here. Have `backup_script` echo the exact timestamped path and
capture it from `run_remote` output (e.g. `BACKUP_PATH=$(run_remote ... | tail -n 1)`), instead of
re-discovering it via `ls`.



─── scripts/deploy.sh:167-168 ───
[bug · medium] Second-level timestamps are not unique: two backups in the same second produce the
same filename, and `tar -czf` will silently overwrite (destroy) the existing archive — which may be
the only rollback point left after pruning to `BACKUP_KEEP`. Add a uniqueness suffix and refuse to
clobber an existing archive.

- ts=\$(date +%Y%m%d-%H%M%S)
+ ts=\$(date +%Y%m%d-%H%M%S)-\$\$
+ [ -e "backups/\${ts}.tar.gz" ] && { echo "备份文件已存在: \${ts}.tar.gz" >&2; exit 1; }
  tar -czf "backups/\${ts}.tar.gz" \\


─── scripts/deploy.sh:84-85 ───
[security · high] `StrictHostKeyChecking=no` combined with `UserKnownHostsFile=/dev/null` disables
server identity verification for every `ssh`/`scp` in this script, including the `--with-env` upload
that carries secrets and the code upload that is then executed by systemd. An attacker positioned
between you and the host can silently substitute the server and receive the
private-key-authenticated session / poisoned payloads. Prefer pinning the expected host key (`-o
UserKnownHostsFile=<pinned known_hosts> -o StrictHostKeyChecking=yes`) or checking
`ssh-keyscan`/fingerprint once during pre-flight.



─── scripts/deploy.sh:405-405 ───
[bug · medium] This `run_remote` is not guarded. Under `set -euo pipefail`, a failed `chmod` aborts
the script after files have already been uploaded but before the restart/rollback phase, leaving the
server in a half-deployed state with no rollback. Wrap it like the other remote steps (`|| warn ...;
TRANSFER_FAILED=1`) or at least downgrade to a warning.

-     run_remote "收紧 .env 权限" "chmod 600 '${REMOTE_DIR}/${ENV_FILE}'"
+     run_remote "收紧 .env 权限" "chmod 600 '${REMOTE_DIR}/${ENV_FILE}'" || warn ".env 权限收紧失败（不影响部署，继续）"


─── scripts/deploy.sh:27-27 ───
[security · medium] The deploy key lives at a fixed, predictable path inside the world-writable
`/tmp`. On a multi-user machine another local user can pre-create that path (or a symlink to their
own file) before this script runs; the `chmod 600` performed below would then operate on/trust
attacker-controlled content, and the deploy would authenticate with an unintended key. Store the key
under `~/.ssh` (or `$XDG_RUNTIME_DIR`) with 600 permissions instead.



─── .github/workflows/ci.yml:11-13 ───
[security · medium] No `permissions:` block is declared, so the workflow runs with the repository's
default `GITHUB_TOKEN` scopes (which can be read/write depending on repo settings). This job only
needs to read the checkout, so least-privilege should be declared explicitly. Also,
`timeout-minutes` is missing — a hanging `pytest`/`pip install` step will consume runner minutes
until the 6h platform default. Suggest adding both at job level.

+ permissions:
+   contents: read
+ 
  jobs:
    test:
      runs-on: ubuntu-latest
+     timeout-minutes: 20


─── .github/workflows/ci.yml:8-9 ───
[performance · low] Push/PR triggers without a `concurrency` group mean every new commit to a PR
branch spawns a full run (compileall + pip install + chunk build + pytest) while the previous one
keeps burning a runner. Add a concurrency group keyed on ref with `cancel-in-progress` so superseded
runs are cancelled.

    pull_request:
    workflow_dispatch:
+ 
+ concurrency:
+   group: ci-${{ github.workflow }}-${{ github.ref }}
+   cancel-in-progress: true


─── .github/workflows/ci.yml:55-55 ───
[security · medium] The comment above says the goal is to catch secrets that have *ever* entered git
history, but `git ls-files` only lists currently tracked files at HEAD, and the checkout is shallow
(default `fetch-depth: 1`), so anything deleted in a later commit is invisible. Either scan history
(`git log --all --diff-filter=A --name-only` with `fetch-depth: 0`) or use a dedicated scanner (e.g.
gitleaks). Additionally the pattern misses realistic leak paths: `.env.local`/`.env.production`,
`*.sqlite`, `*.pem`, `.streamlit/secrets.toml`, etc.



─── .github/workflows/ci.yml:53-54 ───
[bug · medium] This guard runs last, so it is skipped whenever any earlier step fails (compileall,
chunk build, pytest). A leaked `.env` should be reported regardless of test outcomes — move this
step right after `actions/checkout` (cheapest step, fails fast) or add `if: always()`.

        - name: 检查敏感文件
+         if: always()
          run: |



──────── Project Summary ────────

### Top Issues

1. **Deploy pipeline is not atomic and rollback is unreliable (`scripts/deploy.sh`).** `equipment.db` is `scp`'d directly onto the live SQLite file while `badminton-rag`/`badminton-admin` are still running; the copy is not atomic and the running process may hold page cache, so reads during copy see a torn database. The rollback path is worse: it restarts only `${SERVICE_NAME}`, leaving `badminton-admin` executing pre-rollback code against reverted on-disk files, and it never refreshes `/tmp/badminton-rag-restart.ts`, so `check_log` replays the *failed* deployment's journal errors and reports failure after a successful rollback. Root cause: no stop/backup/swap/restart sequencing and no rollback state reset.

2. **Backup identification races and silently destroys rollback points (`scripts/deploy.sh`).** `BACKUP_PATH` is resolved via `ls -1t | head -n 1` instead of the exact archive this run produced, so a concurrent deploy can make rollback restore the *other* run's snapshot. Second-level timestamps collide, and `tar -czf` overwrites silently — potentially clobbering the only remaining archive after pruning to `BACKUP_KEEP`.

3. **SSH host verification is disabled globally and the deploy key sits in world-writable `/tmp` (`scripts/deploy.sh`).** `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null` applies to the `--with-env` secret upload and to the code upload that systemd later executes — a textbook MITM path to remote code execution. Separately, the fixed key path under `/tmp` lets another local user pre-create the file/symlink before `chmod 600` runs.

4. **Logging in `tools/query_log.py` fails silently and leaks connections.** Every caller does `with _conn() as conn:` but `sqlite3.Connection.__enter__` only commits/rolls back — it never closes, so connections accumulate until GC. Compounding this, the write path catches `Exception` and `pass`es, so schema mismatch, `database is locked`, disk full, or `TypeError` drops every entry with zero diagnostics.

5. **Session analytics in `tools/query_log.py` are both collision-prone and unindexed.** Session IDs keep only 8 hex chars (32 bits), which silently merges distinct users' turn chains under the birthday bound (~tens of thousands of sessions) — exactly the scale `sessions_recent()` and `stats()` are meant to report on. Meanwhile only `ts` is indexed while all hot paths (`by_session()`, `sessions_recent()`'s `GROUP BY` + correlated subquery, `COUNT(DISTINCT session_id)`) filter on `session_id`.

6. **"Today" filtering is wrong for non-UTC timezones (`tools/query_log.py`).** `ts` is written with local-time `datetime.now().isoformat()` while `date('now')` is the UTC date; in UTC+8 the filter still matches yesterday's local records between 00:00 and the UTC rollover.

7. **Evaluation metrics in `run_eval.py` can be corrupted or crash.** `lstrip("0123456789.-、) ")` strips leading digits from legitimate rewrites (`60 seconds interval` → `seconds interval`, `4.74 grams` → `grams`) — and the eval set deliberately contains numeric content. Recording also happens twice: `hit_count += hit` / `details.append` run before printing and `generate()`, while the enclosing `except` unconditionally appends `(question, False)`, so a late exception records one question as both hit and miss. `RAG_EVAL_LIMIT=0` yields an empty `subset` and a `ZeroDivisionError` before any summary prints.

8. **Eval config defaults diverge from the real generation path (`run_eval.py`).** `CHAT_MODEL` and `CHAT_BASE_URL` default to `""`, whereas `answer_generator.py` defaults to `deepseek-chat` / `https://api.deepseek.com` and validates API keys — so a missing env var silently constructs a client with blank model/base URL instead of failing fast.

9. **CI secret scanning gives false assurance (`.github/workflows/ci.yml`).** The comment claims detection of secrets that "ever entered git history," but `git ls-files` only sees HEAD-tracked files and the checkout is shallow (`fetch-depth: 1`), so deleted secrets are invisible. The step also runs last, so it is skipped whenever compileall, chunk build, or pytest fails — precisely when a leak matters.

10. **CI workflow lacks least-privilege and lifecycle controls (`.github/workflows/ci.yml`).** No `permissions:` block (default token scopes, potentially read/write), no `timeout-minutes`, and no `concurrency` group with `cancel-in-progress` — superseded PR runs keep burning runners alongside the new one.

### Module Hotspots

- **`scripts/deploy.sh`** — 8 of 23 comments, and the highest severity density: security (host key verification, `/tmp` key), data integrity (live SQLite overwrite), and rollback correctness (admin service, stale restart timestamp, backup race, timestamp collision). Single unguarded `run_remote` (`chmod`) also aborts mid-deploy under `set -euo pipefail`, leaving files uploaded and services unrestarted with no rollback.
- **`run_eval.py`** — 6 comments spanning correctness (digit stripping, double-counting, empty subset), configuration drift vs `answer_generator.py`, and dead code (`rrf_fuse` import, unused `SYSTEM_PROMPT`).
- **`tools/query_log.py`** — 5 comments but all systemic (connection lifetime, silent exception swallowing, ID entropy, missing index, timezone).
- **`.github/workflows/ci.yml`** — 4 comments, all hardening/lifecycle rather than logic.

### Cross-Cutting Concerns

- **Silent failure over fail-fast.** `tools/query_log.py` swallows every write exception with `pass`; `run_eval.py` mixes partial recording with an unconditional failure append; `run_eval.py` client construction accepts blank model/base URL instead of validating like `answer_generator.py` does. Across the repo, failures degrade quietly rather than surfacing.
- **Non-atomic state mutation.** `scp` over a live SQLite file (`scripts/deploy.sh`), `tar` overwrite on timestamp collision (`scripts/deploy.sh`), and backup selection by "newest" rather than "this run's" — the same missing pattern of deterministic, uniquely-named, quiesced state transitions.
- **Dead/divergent configuration.** `run_eval.py` carries an unused `rrf_fuse` import and an unused `SYSTEM_PROMPT` that implies control over prompts it doesn't have; `CHAT_MODEL`/`CHAT_BASE_URL` defaults contradict `answer_generator.py`. Readers cannot tell which constants are live.
- **No regression coverage for the risky surfaces.** CI runs `pytest` on the Python code, but nothing validates `scripts/deploy.sh` (shellcheck/dry-run) or asserts eval metric invariants — the two areas with the most severe comments. (No test files were flagged in the review, which is itself a signal for `query_log.py` and `run_eval.py`.)

### Quick Wins

- Add `CREATE INDEX ... ON logs(session_id)` (and likely `(session_id, ts)`) in `tools/query_log.py`; widen session IDs from 8 hex chars to the full UUID or ≥128 bits.
- Replace `except Exception: pass` in the `query_log.py` write path with logged-and-continue (or count/log to stderr) so outages are diagnosable; explicitly `close()` connections or use `contextlib.closing`.
- Store `ts` as UTC (`datetime.now(timezone.utc)`) or compare with `date('now','localtime')` consistently.
- Delete the `rrf_fuse` import and `SYSTEM_PROMPT` from `run_eval.py`; make `CHAT_MODEL`/`CHAT_BASE_URL` default to the same values as `answer_generator.py`.
- Guard the empty `subset` before `hit_count / len(subset)` in `run_eval.py`, and move result recording after `generate()`/printing so a failure records once.
- In `scripts/deploy.sh`: wrap the bare `run_remote` (`chmod`) with `|| warn`/`|| fail-with-rollback`, add a uniqueness suffix to backup names and use the returned filename, refresh `/tmp/badminton-rag-restart.ts` inside `rollback_script`, and restart `badminton-admin` alongside `${SERVICE_NAME}`.
- In `.github/workflows/ci.yml`: add `permissions: contents: read`, `timeout-minutes`, and a `concurrency` group with `cancel-in-progress: true`; move the secret-scan step to just after `actions/checkout` (or mark it `if: always()`).
