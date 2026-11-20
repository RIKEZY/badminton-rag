
─── admin/admin_app.py:18-18 ───
[maintainability · low] Unused import: `recent` is never referenced in this file (only `by_session`,
`overview`, `sessions_recent`, `stats` are used). Remove it to avoid dead code and a misleading
signal that the page renders the flat recent-log list.

- from tools.query_log import by_session, overview, recent, sessions_recent, stats
+ from tools.query_log import by_session, overview, sessions_recent, stats


─── admin/admin_app.py:38-42 ───
[security · medium] The password check uses plain `==` on a secret (non-constant-time comparison)
and the form has no throttle/lockout, so an attacker reaching this page can brute-force the admin
password at full Streamlit request rate. Prefer `secrets.compare_digest`, and add a simple attempt
counter / back-off in `st.session_state`.

-             if pwd == PASSWORD:
+             if secrets.compare_digest(pwd.encode("utf-8"), PASSWORD.encode("utf-8")):
                  st.session_state.admin_ok = True
+                 st.session_state.pop("admin_fails", None)
                  st.rerun()
              else:
+                 st.session_state["admin_fails"] = st.session_state.get("admin_fails", 0) + 1
+                 time.sleep(min(st.session_state["admin_fails"], 3))  # 粗粒度退避
                  st.error("密码错误")


─── admin/admin_app.py:51-51 ───
[bug · medium] `overview()` opens/creates the SQLite DB (`_conn()` does `mkdir` + `connect` +
`executescript`) and can raise `sqlite3.OperationalError`/`PermissionError`/"database is locked"
when `QUERY_LOG_DB` points at a path the app user cannot write, or when a concurrent writer holds
the 5s timeout. Nothing here (nor for `stats()`, `sessions_recent()`, `by_session()`) catches it, so
the admin page dies with a raw traceback instead of a readable message — note that the write path
deliberately swallows errors, so failures only surface on the read path.

+ try:
- ov = overview()
+     ov = overview()
+ except Exception as exc:  # 读日志失败时给出可操作的提示，而不是整页 traceback
+     st.error(f"读取访问日志失败：{exc}\n\n请检查 `QUERY_LOG_DB` 路径是否存在且当前用户可读写。")
+     st.stop()


─── admin/admin_app.py:93-93 ───
[performance · low] Every Streamlit interaction (button click, selectbox change, text input)
re-executes this whole script, so all four SQLite queries — `overview()`, `stats()`,
`sessions_recent(40)` and `by_session()` — run again on each rerun, and `by_session()` re-runs even
when the selection did not change. Wrapping the read helpers with `@st.cache_data(ttl=...)` (e.g. in
a thin cached wrapper module) or at least gating the detail query on a changed selection would
remove the repeated I/O.



─── admin/admin_app.py:126-126 ───
[security · low] User-submitted `question`/`answer` text is interpolated straight into
`st.markdown`/`st.caption`, so a crafted question can inject Markdown (links, images, headings,
blockquote breaking) into the authenticated admin view — a phishing/content-spoofing vector against
the operator viewing untrusted visitor input. Escape or render untrusted text with `st.text()` (or
neutralize `[`, `` ` ``, `#`, `!` before interpolation).



─── hybrid.py:115-119 ───
[high] The `__main__` demo block cannot run — three separate defects:
1. `vector_search_idx(chunks)` / `bm25_search_idx(chunks)` are missing required positional args
(`client, chunks, vecs, query` and `bm25, chunks, query` respectively) → immediate `TypeError`.
Every other caller in the repo (app.py:216, run_eval.py:168, tools/hybrid_check.py:47) passes the
full argument list.
2. `BM25Okapi(chunks)` is constructed from raw chunk **dicts** instead of a tokenized corpus, so
document length/term-frequency statistics are garbage; this file already provides
`build_bm25(chunks)` for exactly this purpose.
3. `json.load(open(...))` bypasses the context manager, leaking the file handle on error, and the
two result variables are never used (no print/return), so the block computes nothing observable.

Either make the smoke test actually exercise the pipeline or delete the block, since it currently
misleads readers into thinking it is a working example.

  if __name__ == "__main__":
-     chunks = json.load(open("chunks.json", encoding="utf-8"))
-     bm25 = BM25Okapi(chunks)
-     vector_hits = vector_search_idx(chunks)
-     bm25_hits = bm25_search_idx(chunks)
+     from openai import OpenAI
+ 
+     with open("chunks.json", encoding="utf-8") as f:
+         chunks = json.load(f)
+     bm25 = build_bm25(chunks)
+ 
+     client = OpenAI(...)          # 与 index_builder 保持一致的构造方式
+     vecs = load_vecs(chunks)
+     query = "发球时球拍的位置"
+     for score, i in vector_search_idx(client, chunks, vecs, query, k=5):
+         print(round(score, 4), i, chunks[i]["text"][:40])
+     for score, i in bm25_search_idx(bm25, chunks, query, k=5):
+         print(round(score, 4), i, chunks[i]["text"][:40])


─── hybrid.py:60-62 ───
[medium] BM25 results are truncated purely by rank, without dropping non-matching documents.
`get_scores` returns exactly `0.0` for every chunk that contains none of the query tokens, and this
code still returns the top `k` of them.

Because `sorted(..., reverse=True)` is stable, when fewer than `k` chunks actually match, the
zero-score filler comes out in **ascending index order** (chunk 0, 1, 2, …), and `rrf_fuse` throws
away the score (`for rank, (_, idx) in enumerate(hits, 1)`) and credits those chunks with
`1/(k+rank)` votes anyway. That is a real ranking bug rather than a quality nit: the
term-direct-query path (`term_hit_lists` in app.py:228 / tools/trace_pipeline.py:61) frequently
matches nothing, so an unmatched term silently promotes the first `k` chunks of the corpus into the
fusion, and the effect is worst exactly in `fuse_by_language`, where that group competes as a whole
language side.

Filter zero scores so a path that found nothing contributes no votes.

      scores = bm25.get_scores(tokenize(query))
-     order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
-     return [(float(scores[i]), i) for i in order[:k]]
+     ranked = sorted(((float(s), i) for i, s in enumerate(scores) if s > 0),
+                     reverse=True)
+     return ranked[:k]


─── hybrid.py:58-58 ───
[low] The `chunks` parameter is never read in the body — the function only needs `bm25`, `query` and
`k`. Same for `vector_search_idx`, which never touches `chunks` either (it uses `vecs` and `query`).

Beyond being dead, the parameter is actively misleading: it implies the returned indices are
validated against `chunks`, so a caller that builds `bm25` from one chunk list and passes a
different (e.g. re-chunked or filtered) list gets silently wrong indices with no error. Either drop
the parameter (all 8 call sites would need updating) or assert the alignment so the implicit
contract is enforced.

  def bm25_search_idx(bm25: BM25Okapi, chunks: list[dict], query: str, k: int = 5):
+     assert bm25.corpus_size == len(chunks), "BM25 索引与 chunks 不同源"


─── hybrid.py:52-55 ───
[low] Two issues on the per-request hot path (app.py:215-233 runs 4 of these in parallel per query):

1. `chunks` is unused in the body (see the same problem in `bm25_search_idx`); the index/score
alignment it implies is never checked.
2. `sorted(range(len(scores)), key=lambda i: scores[i])` is a full O(n log n) sort that materializes
a NumPy scalar per element and compares them in Python — several times slower than the vectorized
path, and it sorts the whole corpus to keep only `k` items. `index_builder.search`
(index_builder.py:149) already uses `np.argsort`, so this file is inconsistent with the established
idiom. `np.argpartition` gets the top-k in O(n).

Also worth noting: cosine scores can be negative, and like the BM25 side this returns `k` hits
regardless of relevance, so a completely off-topic query still injects a full slate of RRF votes.

      q = embed_query(client, query)
-     scores = vecs @ q
-     order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
-     return [(float(scores[i]), i) for i in order[:k]]
+     scores = vecs @ q                       # 归一化后点积 = 余弦相似度
+     k = min(k, len(scores))
+     cand = np.argpartition(-scores, k - 1)[:k] if k else []
+     cand = cand[np.argsort(-scores[cand])]
+     return [(float(scores[i]), i) for i in cand if scores[i] > 0]


─── index_builder.py:106-108 ───
[bug · high] Vector cache invalidation contradicts the design stated in the module docstring.
`build_chunks()` correctly calls `_corpus_changed_since(CHUNK_CACHE)`, but `build_vectors()` only
compares the **row count** with `len(chunks)`. Any corpus edit that keeps the chunk count identical
(wording fix inside a clause, a page re-typed, a document replaced with an equally-structured one)
silently reuses the old vectors — exactly the "cache exists ⇒ trust it" failure this file was
written to avoid, and the answers will be wrong with no signal. A model swap (`EMBED_MODEL`) is
equally invisible: same row count, different embedding space (and possibly different dimensionality
→ `vecs @ q` raises `ValueError`). Suggest gating on corpus mtime here too and persisting the
model/dim in a sidecar meta file that is compared before reuse.

-     if VEC_CACHE.exists():
+     if VEC_CACHE.exists() and not _corpus_changed_since(VEC_CACHE):
          vecs = np.load(VEC_CACHE)
-         if len(vecs) == len(chunks):
+         if vecs.ndim == 2 and len(vecs) == len(chunks) and _meta_matches(vecs):


─── index_builder.py:128-130 ───
[bug · medium] Two division/shape hazards on this line:
1. If the corpus yields no chunks (e.g. `data/` exists but contains only unsupported file types —
`load_documents()` then returns `[]`, unlike its own `main()` which exits with a friendly message),
`all_vecs` is `[]`, `np.array([])` is 1-D, and `np.linalg.norm(vecs, axis=1)` raises a cryptic
`AxisError` after the loop.
2. A zero-norm embedding (empty/whitespace-only batch entry, which some providers return instead of
erroring) turns the whole row into `NaN`; those rows then pollute `search()`'s scores.
Guard the empty case and mask zero norms.

+     if not all_vecs:
+         sys.exit("没有可向量化的块：请确认语料目录里有可解析的 pdf/txt/md")
+ 
      vecs = np.array(all_vecs, dtype=np.float32)
      # 归一化：之后用点积就等于余弦相似度，省一次除法
-     vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
+     norms = np.linalg.norm(vecs, axis=1, keepdims=True)
+     vecs /= np.where(norms == 0, 1.0, norms)


─── index_builder.py:119-119 ───
[performance · low] The batch loop has no retry and no checkpoint: one transient 429/timeout/network
error after 20 of 21 batches aborts `main()` and discards every embedding already paid for, which
defeats the stated goal of this function ("第二次跑就不用再花钱") — the next run re-embeds from scratch. Wrap
the call in a bounded retry with backoff and flush partial results (e.g. save `all_vecs` to a temp
`.npy` every N batches) so a restart resumes instead of re-billing.



─── index_builder.py:97-99 ───
[bug · low] Cache writes are in place, so an interrupted build (Ctrl+C mid-run, OOM, killed deploy)
leaves a truncated `chunks_*.json` / `vectors_*.npy`. On the next run `json.loads(...)` raises
`JSONDecodeError` (or `np.load` raises) and the script dies with a confusing traceback instead of
rebuilding — worse, `app.py`'s `load_index()` propagates that failure to every request. Write to a
temp file in the same directory and `os.replace()` it (atomic on POSIX and Windows), and treat a
corrupt cache as "rebuild" rather than a hard error.

-     CHUNK_CACHE.write_text(
+     tmp = CHUNK_CACHE.with_suffix(".json.tmp")
+     tmp.write_text(
          json.dumps(chunks, ensure_ascii=False, indent=1), encoding="utf-8"
      )
+     os.replace(tmp, CHUNK_CACHE)


─── answer_generator.py:101-101 ───
[bug · medium] `generate()` is the shared answer path used by `app.py`, `run_eval.py`,
`agent_tools.py` and `tools/compare_sql_vs_rag.py`, but it indexes/reads the response without any
validation:
- `resp.choices[0]` raises `IndexError` when a provider returns an empty `choices` array
(content-filter refusals, some compatibility layers).
- `resp.usage.total_tokens` raises `AttributeError` when `usage` is `None` — exactly the class of
provider the streaming path already works around, so the assumption is inconsistent with the rest of
this file.
- `message.content` can be `None`, which breaks the declared `tuple[str, int]` and then
`build_context`/`st.write` callers get a `None` answer.

Guard all three so the function returns its declared types instead of crashing mid-iteration.

-     return resp.choices[0].message.content, resp.usage.total_tokens
+     answer = (resp.choices[0].message.content or "") if resp.choices else ""
+     tokens = getattr(resp.usage, "total_tokens", 0) if resp.usage else 0
+     return answer, tokens


─── answer_generator.py:137-138 ───
[bug · medium] Catching bare `Exception` here is far broader than the failure being handled ("this
provider doesn't support `stream_options`"). Authentication errors, 429 rate limits,
timeouts/network failures and 400 malformed-request errors all land in this `except`, get no logging
at all, and silently trigger a **second** `create()` call — doubling latency and cost while hiding
the real root cause (and if the failure was genuine, the user just sees the retry fail with a
confusing traceback from the fallback line).

Narrow it to the exceptions a compatibility layer actually raises for the unsupported parameter, and
surface the fallback:

-     except Exception:
+     except (TypeError, openai.BadRequestError) as err:
+         print(f"[generate_stream] provider 不支持 stream_options，退回不带 usage 的流：{err}")
          stream = chat_client.chat.completions.create(**kwargs)


─── answer_generator.py:259-260 ───
[bug · medium] No guard for an empty retrieval result. `fuse_by_language` → `rrf_fuse` returns `[]`
whenever the candidate lists are empty (e.g. `data/` is missing/empty so `chunks == []`, or a
filtered corpus yields no hits), and then `build_context([])` returns `""`. The empty context is
still sent to the model, so the system prompt's "资料里没有就说不知道" is the only thing standing between the
user and a fully ungrounded answer — which directly contradicts this file's stated goal of
citation-backed answers. Skip the LLM call (and its cost) instead.

+         if not hits:
+             print("\n未检索到任何资料，跳过回答（请检查 data/ 目录或换一个问法）。")
+             continue
+ 
          context = build_context(hits)
          print(f"\n上下文长度：{len(context)} 字符")


─── answer_generator.py:22-22 ───
[maintainability · low] `search` is imported but never used — the only reference is the
commented-out single-path retrieval line below. Keeping it imported misleads readers into thinking
the plain vector path is still an active option and masks the real retrieval path
(`vector_search_idx` + `bm25_search_idx` + `fuse_by_language`). Drop it from the import (and delete
or clearly mark the stale commented call).

- from index_builder import build_chunks, build_vectors, search
+ from index_builder import build_chunks, build_vectors


─── answer_generator.py:14-15 ───
[maintainability · low] `rrf_fuse` is imported here but never referenced in this file — fusion is
already performed inside `fuse_by_language`. Unused imports like this are dead code that makes the
pipeline look more complex than it is; remove it.

  from hybrid import (bm25_search_idx, build_bm25, fuse_by_language,
-                     rrf_fuse, vector_search_idx)
+                     vector_search_idx)


─── answer_generator.py:224-226 ───
[performance · low] This query-rewrite call omits `**chat_extra()`, unlike `generate()` and
`generate_stream()`. Since it is the first LLM call of every loop iteration, when
`CHAT_DISABLE_THINKING=1` the rewrite still runs full reasoning — paying exactly the 3-4 s the
module comment above says it wants to eliminate, on every question, before any user-visible output.
Also `resp_zh_to_en.choices[0]` is unguarded against an empty `choices` list (same issue as in
`generate()`).

              temperature=0,
+             **chat_extra(),
          )
-         raw_en = (resp_zh_to_en.choices[0].message.content or "").strip()
+         raw_en = (resp_zh_to_en.choices[0].message.content or "").strip() if resp_zh_to_en.choices else ""


─── document_loader.py:108-111 ───
[bug · medium] `chunk_text` has no validation of `size`/`overlap`. When a caller passes `overlap >=
size`, `step = size - overlap` becomes `0` or negative, and the `while` loop never advances nor
satisfies the `start + size >= len(text)` break — it appends the identical piece forever (infinite
loop + unbounded memory growth). Same when `size <= 0` (every slice is empty). Since `experiments/`
tunes `CHUNK_SIZE` while keeping `OVERLAP` fixed, this is one bad parameter away from hanging a
build. Guard the parameters up front.

+     if size <= 0 or not 0 <= overlap < size:
+         raise ValueError(f"无效切块参数：size={size}, overlap={overlap}")
+ 
      if len(text) <= size:
          return [text]
  
      step = size - overlap


─── document_loader.py:50-53 ───
[bug · medium] Two problems here: (1) `PdfReader` keeps the underlying file handle open — the reader
is only released via refcounting, so when `extract_text()`/an encrypted-PDF error propagates, the
traceback keeps the frame (and the handle) alive. pypdf supports the context-manager protocol, so
use `with`. (2) There is no error handling at all: a corrupt or encrypted PDF makes pypdf raise a
bare `FileNotDecryptedError`/`PdfReadError` with no indication of *which* file broke the corpus
build (`load_documents` is called from `index_builder.build_chunks()` and thus from app
startup/tests). Re-raise with file context (`from err`) so failures are diagnosable.

-     reader = PdfReader(str(path))
      pages = []
+     try:
+         with PdfReader(str(path)) as reader:
-     for i, page in enumerate(reader.pages, start=1):
+             for i, page in enumerate(reader.pages, start=1):
-         text = strip_header((page.extract_text() or "").strip())
+                 text = strip_header((page.extract_text() or "").strip())


─── document_loader.py:61-61 ───
[bug · medium] `errors="ignore"` silently discards every byte that isn't valid UTF-8. Given this
project is developed on Windows and the corpus is largely Chinese, a GBK/ANSI-encoded `.txt` would
be loaded as silently truncated/garbled text — the corrupted chunk then flows into embeddings/BM25
with no warning. Additionally, `encoding="utf-8"` keeps a UTF-8 BOM as a leading `\ufeff` character,
which becomes part of the first chunk's text. Prefer `utf-8-sig` plus an explicit fallback/warning
instead of dropping data.

-     text = path.read_text(encoding="utf-8", errors="ignore").strip()
+     try:
+         text = path.read_text(encoding="utf-8-sig").strip()
+     except UnicodeDecodeError:
+         text = path.read_text(encoding="gbk", errors="replace").strip()
+         print(f"  ⚠ {path.name} 不是 UTF-8，已按 GBK 读取，请检查语料编码")


─── document_loader.py:70-71 ───
[maintainability · low] `load_documents` is a library API (imported and called by
`index_builder.build_chunks()`, `tools/chunk_quality.py`, `tests/test_chunking.py`), so terminating
the process here is wrong: `sys.exit()` raises `SystemExit`, which bypasses callers' `except
Exception` handling and kills the serving process at startup/import time. Also, if `RAG_DATA_DIR`
points at a regular file (a plausible typo, e.g. `data_rules_only/bwf_itto.txt`), this check passes
and `iterdir()` then blows up with an obscure `NotADirectoryError`. Raise an exception with a clear
message and let `main()` decide to exit.

-     if not DATA_DIR.exists():
-         sys.exit(f"找不到目录：{DATA_DIR}")
+     if not DATA_DIR.is_dir():
+         raise NotADirectoryError(f"语料目录不存在或不是目录：{DATA_DIR}")

