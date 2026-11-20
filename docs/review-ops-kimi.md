
─── rerank.py:58-59 ───
[maintainability · low] The empty-list fallback is documented, but catching every `Exception`
without any diagnostic also hides programming errors and response-schema regressions, not just
expected request failures. For example, an expired API key, a changed response format, and a bug in
the result conversion all silently disable reranking, making production failures very difficult to
diagnose. Prefer catching the expected HTTP/network/JSON exceptions and logging a warning before
falling back; if the broad fallback is intentional, at least log the caught exception (without
logging the API key).



─── admin/admin_app.py:37-38 ───
[security · medium] Every form submission performs an immediate password check with no throttling,
backoff, or lockout. If this page is network-accessible, attackers can make unlimited online
password guesses. Enforce server-side or reverse-proxy rate limiting for login attempts (and
consider a failure delay/lockout); a counter stored only in `st.session_state` would be bypassable
by starting a new session.



─── admin/admin_app.py:74-74 ───
[bug · medium] The project declares `streamlit>=1.30`, but Streamlit 1.30's `st.dataframe` does not
support the newer string value `width="stretch"` (its width is a pixel integer/`None`). An
installation at the declared lower bound can therefore fail while rendering the dashboard. Either
raise the minimum Streamlit version to one supporting this argument or use the backward-compatible
`use_container_width=True`; apply the fix to all three dataframe calls.

-             width="stretch", hide_index=True,
+             use_container_width=True, hide_index=True,


─── admin/admin_app.py:18-18 ───
[maintainability · low] `recent` is imported but never referenced anywhere in this module. Remove it
from the import list to avoid a dead dependency.

- from tools.query_log import by_session, overview, recent, sessions_recent, stats
+ from tools.query_log import by_session, overview, sessions_recent, stats


─── run_eval.py:23-24 ───
[maintainability · low] `rrf_fuse` is imported but never referenced; this evaluation path uses only
`fuse_by_language`. Remove the unused import so the retrieval pipeline does not misleadingly suggest
that a separate RRF call occurs here.

  from hybrid import (bm25_search_idx, build_bm25, fuse_by_language,
-                     rrf_fuse, vector_search_idx)
+                     vector_search_idx)


─── run_eval.py:77-80 ───
[maintainability · low] `SYSTEM_PROMPT` is never read or passed to `generate`, so it has no effect
on the generated answers. Remove it, or explicitly wire it into answer generation through the
generator's supported system-prompt interface if this behavior is intended.



─── run_eval.py:103-103 ───
[bug · medium] `lstrip` treats its argument as a set of characters, not as a numbering prefix.
Consequently, a valid rewrite beginning with a value—such as `60-second interval...` or `4.74-5.50
grams...`—loses the leading numeric constraint (for example, becoming `second interval...`), which
can change retrieval results. Strip only an actual enumerated-list prefix instead; a small regex
such as `^\d+\s*[.、)-]\s*` (with `import re`) preserves numeric queries.

-         ln = ln.strip().lstrip("0123456789.-、) ").strip()
+         ln = re.sub(r"^\d+\s*[.、)-]\s*", "", ln.strip()).strip()


─── run_eval.py:179-181 ───
[bug · high] The per-question result is recorded before answer generation, while the surrounding
exception handler appends another result unconditionally. If `generate` (or later output processing)
raises, a retrieval miss is printed twice in the final missed-question list; a retrieval hit remains
included in `hit_count` but is also reported as missed. Ensure each question is appended exactly
once—for example, handle answer-generation failures separately from retrieval accounting, or append
in the exception path only when no result has yet been recorded.



─── run_eval.py:205-206 ───
[bug · medium] `RAG_EVAL_LIMIT=0`, or a negative value whose slice excludes every entry, makes
`subset` empty. After the loop, this percentage calculation then divides by `len(subset)` and raises
`ZeroDivisionError` instead of producing a clean empty-evaluation result. Validate that the limit is
positive or guard `not subset` before this summary and return without dividing.

+     if not subset:
+         print("没有可评测的题目，请检查 RAG_EVAL_LIMIT。")
+         return
      print(f"Recall@{TOP_K}: {hit_count}/{len(subset)}"
            f"  ({hit_count / len(subset) * 100:.0f}%)")


─── tools/query_log.py:35-39 ───
[maintainability · medium] `sqlite3.Connection`'s context manager only commits or rolls back; it
does not close the connection. Thus every `with _conn()` call in this module leaves file-descriptor
and SQLite-lock cleanup to refcounting/GC rather than guaranteeing it, and an `executescript()`
failure also has no explicit cleanup. Make `_conn()` a real context manager with `try/finally:
conn.close()`, or use `contextlib.closing` at each call while retaining `with conn:` around the
insert for transaction handling.



─── tools/query_log.py:72-74 ───
[bug · high] `log_query()` stores naive local-time values from `datetime.now()`, but SQLite's
`date('now')` is UTC. On a non-UTC host, the `today` metric includes or excludes the wrong rows
around local midnight; `overview()` repeats the same faulty comparison. Use one clock
consistently—for example, `date('now', 'localtime')` with the current storage format, or store UTC
timestamps and compare UTC dates.



─── tools/query_log.py:92-93 ───
[bug · high] Keeping only 8 hexadecimal characters gives session IDs just 32 bits of entropy.
Birthday collisions reach roughly 50% at 77,000 generated sessions, after which unrelated users'
turns are silently merged by `GROUP BY session_id` / `by_session()` and session counts are
understated. Return the full UUID and truncate only a display label if a short UI identifier is
needed.



─── tools/query_log.py:120-122 ───
[performance · medium] `session_id` is used as a lookup and grouping key, but the schema only
indexes `ts`. This query scans the full, continually growing log; `sessions_recent()` also groups by
`session_id` and performs the correlated `first_q` lookup without a supporting index, potentially
rescanning for each session. Add a composite index on `query_log(session_id, id)` so both
session-chain ordering and the first-question lookup can use it.




──────── Project Summary ────────

### Top Issues

1. **The admin login permits unlimited online password guessing.** `admin/admin_app.py` checks the password immediately on every submission, without throttling, backoff, or lockout. If network-accessible, this is the scan’s clearest security exposure.

2. **Short session IDs can silently merge unrelated users’ query history.** `tools/query_log.py` retains only 8 hexadecimal characters, providing 32 bits of entropy. Birthday collisions approach 50% around 77,000 generated sessions; grouping and lookups by `session_id` can then combine unrelated turns and understate session counts.

3. **Reranking failures are indistinguishable from legitimate empty results.** `rerank.py` catches every `Exception` and returns its documented empty-list fallback without diagnostics. Expired credentials, response-schema changes, and programming errors can therefore silently degrade retrieval rather than surface an actionable failure.

4. **The evaluation path can silently change the behavior it claims to measure.** In `run_eval.py`, prefix removal with `lstrip` treats its argument as a character set and can delete leading numeric constraints from valid rewrites. Separately, `SYSTEM_PROMPT` is never passed to generation, so it has no effect even if the evaluation is intended to exercise that prompt.

5. **Evaluation result accounting is not exception-safe.** `run_eval.py` records a per-question result before generation and then unconditionally appends another result from the surrounding exception handler. Generation or output-processing failures can consequently duplicate entries and corrupt the final missed-question reporting.

6. **SQLite connections are not deterministically closed.** In `tools/query_log.py`, `with sqlite3.Connection(...)` handles commit/rollback but not closure. Repeated `with _conn()` blocks therefore leave descriptor and lock cleanup to garbage collection rather than guaranteeing it.

7. **Session queries will increasingly scan the growing log.** `tools/query_log.py` indexes `ts` but not `session_id`, despite using the latter for lookups, grouping, and the correlated `first_q` lookup. `by_session()` and `sessions_recent()` are particularly exposed as log volume increases.

8. **Daily analytics mix local time with UTC.** `log_query()` stores naive values from `datetime.now()`, while `date('now')` uses UTC. On non-UTC hosts, both the `today` metric and `overview()` can include or exclude the wrong rows around local midnight.

9. **Two supported edge configurations can fail at runtime.** `run_eval.py` divides by `len(subset)` when `RAG_EVAL_LIMIT=0` or a negative slice produces an empty evaluation. `admin/admin_app.py` uses `width="stretch"` despite declaring `streamlit>=1.30`, whose `st.dataframe` API does not support that string value.

### Module Hotspots

- **`run_eval.py` — 5 of 13 comments:** The largest concentration, dominated by evaluation validity: destructive rewrite cleanup, an ineffective system prompt, duplicate exception-path results, and empty-subset failure. These issues can make reported results misleading even when the command appears to complete successfully.
- **`tools/query_log.py` — 4 of 13 comments:** The broadest operational risk cluster, spanning session-data integrity, timezone correctness, connection lifecycle, and query scalability.
- **`admin/admin_app.py` — 3 of 13 comments:** Lower comment count but high severity because it contains the unthrottled password check. It also has a dependency/API compatibility problem and dead code.
- **`rerank.py`:** Only one comment, but a severity outlier: its broad fallback can conceal infrastructure, schema, and programming failures across every reranking request.

### Cross-Cutting Concerns

- **Error paths favor plausible-looking output over trustworthy diagnostics.** `rerank.py` converts all failures into an empty result, while `run_eval.py` can record multiple outcomes for one question or crash only after processing an empty subset. Fallback and exception paths need explicit, distinguishable semantics.
- **Silent data corruption is more prominent than explicit failure.** Numeric rewrite damage in `run_eval.py`, session collisions and local/UTC comparisons in `tools/query_log.py`, and duplicate evaluation records can all produce plausible but incorrect output.
- **Declarations and apparent configuration do not always match execution.** The Streamlit lower bound in `admin/admin_app.py` does not support the API used; `SYSTEM_PROMPT` in `run_eval.py` suggests generation behavior that never occurs. Unused `rrf_fuse` and `recent` imports further obscure which pipeline paths are actually active.

### Quick Wins

- **Make `run_eval.py` deterministic:** replace `lstrip` with exact prefix removal, handle an empty subset before calculating percentages, and append each question’s result on exactly one path. Add small regressions for numeric-leading rewrites, generation exceptions, and `RAG_EVAL_LIMIT=0`.
- **Narrow rerank fallback handling:** catch expected request/API failures, emit a diagnostic without secrets, and allow schema or programming errors to surface rather than treating them as empty rerank results.
- **Harden query logging with localized changes:** explicitly close connections, standardize timestamps and comparisons on UTC, add an index beginning with `session_id` after checking the query plans, and use substantially longer IDs for new sessions.
- **Reduce admin exposure and compatibility drift:** configure reverse-proxy login rate limiting where available, and either raise the Streamlit minimum to a compatible release or use sizing supported at 1.30.
- **Remove misleading dead code:** delete the unused `recent` and `rrf_fuse` imports; wire `SYSTEM_PROMPT` into the generator’s supported interface if intended, otherwise remove it.
