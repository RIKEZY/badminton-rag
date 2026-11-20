
─── index_builder.py:106-108 ───
[bug · high] The vector cache is validated only by row count, not by freshness. If the corpus is
updated and `build_chunks()` rebuilds chunks that happen to keep the same count (e.g., editing text
within existing pages/clauses), `len(vecs) == len(chunks)` still passes and stale vectors are
silently used against new chunk texts — exactly the silent wrong-answer failure mode the module
docstring warns about. Validate against the chunk cache's mtime as well, e.g. also require
`VEC_CACHE.stat().st_mtime >= CHUNK_CACHE.stat().st_mtime` (vectors are always written after the
chunk cache), or reuse `_corpus_changed_since(VEC_CACHE)`.

-     if VEC_CACHE.exists():
+     if VEC_CACHE.exists() and not _corpus_changed_since(VEC_CACHE) \
+             and (not CHUNK_CACHE.exists()
+                  or VEC_CACHE.stat().st_mtime >= CHUNK_CACHE.stat().st_mtime):
          vecs = np.load(VEC_CACHE)
          if len(vecs) == len(chunks):


─── index_builder.py:128-130 ───
[bug · medium] Empty-corpus edge case: `load_documents()` can legitimately return `[]` (e.g.,
DATA_DIR contains only unsupported/empty files), so `chunks` can be empty. Then `all_vecs` is `[]`,
`np.array([], dtype=np.float32)` has shape `(0,)`, and `np.linalg.norm(vecs, axis=1, ...)` raises
`numpy.AxisError` (axis 1 out of bounds for a 1-D array). Guard early, e.g. `if not chunks:
sys.exit("语料为空，无法构建向量索引")` in `build_vectors` (or check in `main` after `build_chunks`), instead of
crashing with an obscure numpy error after caching an empty chunk list.



─── index_builder.py:66-67 ───
[bug · low] Staleness detection misses file deletions: this only checks whether any remaining corpus
file is newer than the cache. If a corpus file is removed (without touching the others), the cache
is considered fresh and chunks from the deleted document keep being served. Consider also
invalidating when the cached chunk `source` set no longer matches the current corpus file set, or
comparing the corpus file count/names against what was cached.



─── document_loader.py:108-111 ───
[bug · medium] `chunk_text` does not validate `size`/`overlap`. If a caller passes `overlap >=
size`, `step = size - overlap` is <= 0, so `start` never advances and the `while` loop runs forever,
appending duplicate chunks until memory is exhausted. Also, an empty `text` falls into the
`len(text) <= size` branch and returns `[""]` (a chunk with empty text) instead of `[]`. Add a guard
for invalid parameters and empty input.

+     if size <= 0 or not (0 <= overlap < size):
+         raise ValueError(f"require size > 0 and 0 <= overlap < size, got size={size}, overlap={overlap}")
+     if not text:
+         return []
      if len(text) <= size:
          return [text]
  
      step = size - overlap


─── answer_generator.py:137-138 ───
[bug · high] This `except Exception` is far broader than the failure it is meant to handle (server
rejecting `stream_options`). It also swallows authentication errors, rate limits, network failures,
etc., and then silently re-issues the same paid request without `include_usage` — duplicating cost
and masking the real error (the retry will usually fail again with the same underlying problem, or
succeed while hiding a transient fault). Narrow the catch to the specific "unsupported parameter"
error, e.g. `openai.BadRequestError` (optionally inspecting the error message/code), and let other
exceptions propagate.

-     except Exception:
+     except BadRequestError:  # from openai import BadRequestError; only fall back for unsupported stream_options
          stream = chat_client.chat.completions.create(**kwargs)


─── answer_generator.py:101-101 ───
[bug · medium] `resp.choices[0]`, `.message.content`, and `resp.usage.total_tokens` are dereferenced
without guards. OpenAI-compatible gateways can return an empty `choices` list, `content=None` (e.g.
when the model only emits reasoning/tool output), or `usage=None`. That would raise
`IndexError`/`AttributeError` here or violate the declared `tuple[str, int]` return type by
returning `None` as the answer. Guard these fields before returning.

-     return resp.choices[0].message.content, resp.usage.total_tokens
+     content = (resp.choices[0].message.content or "") if resp.choices else ""
+     tokens = resp.usage.total_tokens if resp.usage else 0
+     return content, tokens


─── answer_generator.py:219-220 ───
[maintainability · medium] The query-rewrite prompt contradicts itself: Task/Constraints demand a
single verbatim translation ("只输出翻译后的英文问句", "不要输出任何解释"), while the Output section demands 3
different English lines. With `temperature=0` the model may follow either instruction, making
`queries` non-deterministically 1 or 3 entries and weakening the intended multi-query English
retrieval. Align the Task/Constraints wording with the 3-line Output requirement.



─── answer_generator.py:222-225 ───
[bug · medium] Unlike `generate()`/`generate_stream()`, this call omits `**chat_extra()`, so
`CHAT_DISABLE_THINKING` is inconsistently applied — with a thinking-enabled model this rewrite step
still pays the 3–4s "thinking" latency the flag is meant to remove, and the reasoning text may leak
into `raw_en`. Also, this API call is not wrapped in any error handling inside the REPL `while True`
loop: a single transient API failure aborts the whole interactive session instead of just skipping
that question.

                  {"role": "user", "content": question},
              ],
              temperature=0,
+             **chat_extra(),
          )


─── answer_generator.py:259-260 ───
[bug · medium] When retrieval yields no hits (e.g. empty corpus or all lists filtered out),
`build_context` returns `""` and `generate()` is still called with an empty 资料 section — spending
tokens to ask the model an ungrounded question. Short-circuit to a "资料中未找到相关内容/不知道" response when
`hits` is empty instead of calling the chat API.

+         if not hits:
+             print("\n回答：\n不知道（未检索到相关资料）")
+             continue
          context = build_context(hits)
          print(f"\n上下文长度：{len(context)} 字符")


─── answer_generator.py:14-15 ───
[maintainability · low] Dead imports in this file: `rrf_fuse` (from `hybrid`) is never referenced —
fusion is done via `fuse_by_language` — and `search` (from `index_builder`) is only referenced in
the commented-out pure-vector retrieval block in `main()`. Remove both unused imports, and remove
the commented-out alternate retrieval block as well (it references an undefined variable
`translated_question`, so it cannot be re-enabled as-is).

  from hybrid import (bm25_search_idx, build_bm25, fuse_by_language,
-                     rrf_fuse, vector_search_idx)
+                     vector_search_idx)


─── chunker.py:158-159 ───
[bug · high] The clause-promotion guard can never fire for intro blocks: when `prev["clause"]` is
`""`, `"".split(".")` yields `[""]` (length 1), which is never greater than the incoming clause's
segment count. So after an intro block absorbs `14.2.1`, the merged chunk keeps `clause=""`,
`prev_parent` stays empty, and `not prev_parent` remains true — every following clause (even
`14.3.x`, `15.x`, ...) keeps chaining into the same chunk until `max_len` is hit, and the chunk
loses all clause attribution. Promote the clause when the previous one is empty as well.

-                 if len(c["clause"].split(".")) < len(prev["clause"].split(".")):
+                 if not prev["clause"] or len(c["clause"].split(".")) < len(prev["clause"].split(".")):
                      prev["clause"] = c["clause"]


─── chunker.py:152-152 ───
[bug · medium] `same_parent` has no chapter-boundary guard. Because `not prev_parent` is true for
any unnumbered intro block (and, per the promotion bug above, stays true after merging), an intro
chunk at the end of one chapter can be glued to clauses of the *next* chapter. The merged chunk
retains `prev["chapter"]`/`prev["page"]` describing only the first block, so the hierarchical prefix
added later mislabels the appended text. Removing the same-page restriction is documented as
intentional, but chapter equality should still be required, e.g. `same_parent = (prev_parent ==
curr_parent or not prev_parent) and prev["chapter"] == c["chapter"]`.

-             same_parent = prev_parent == curr_parent or not prev_parent
+             same_parent = (prev_parent == curr_parent or not prev_parent) and prev["chapter"] == c["chapter"]


─── chunker.py:36-38 ───
[bug · medium] Chapter/clause state is re-initialised for every page because `split_page_by_clause`
is called per page from `chunk_document`. A clause whose body continues at the top of the next page
hits neither `CHAPTER_RE` nor `CLAUSE_RE`, so it falls into the `else` branch with `clause == ""`
and is emitted as an unnumbered "chapter intro" chunk with empty `clause`/`chapter` and no prefix —
silently losing its legal context (and, via `not prev_parent` in `merge_siblings`, it can then chain
unrelated clauses). Consider carrying `chapter_no`/`chapter_title`/`clause` across pages (e.g. pass
the previous page's ending state in, or split the concatenated document once).



─── chunker.py:198-198 ───
[bug · medium] `step = max_len - 100` is unvalidated: for `max_len == 100` the step is 0 and
`range(0, len(para), 0)` raises `ValueError`; for `max_len < 100` the step is negative, `range` is
empty, and the entire long paragraph is silently dropped (data loss). `max_len` is a caller-supplied
parameter, so clamp it, e.g. `step = max(1, max_len - 100)` (or validate `max_len > 100` up front).

-                 step = max_len - 100
+                 step = max(1, max_len - 100)


─── chunker.py:279-279 ───
[bug · low] `total / original_chars` raises `ZeroDivisionError` when the caller passes
`original_chars=0` while `chunks` is non-empty (the early return only guards the empty-chunks case).
Guard the divisor, e.g. compute the ratio only when `original_chars > 0` and print `n/a` otherwise.

-     print(f"总字符      : {total:,}（原文 {original_chars:,}，比率 {total / original_chars:.2f}）")
+     ratio = f"{total / original_chars:.2f}" if original_chars else "n/a"
+     print(f"总字符      : {total:,}（原文 {original_chars:,}，比率 {ratio}）")


─── agent_core.py:172-175 ───
[bug · medium] This broad `except Exception` wraps the entire LLM call plus JSON parsing and
discards the exception with no logging. API/auth/network outages are silently converted into a fake
`answer` decision (when observations exist) or a forced `search_docs`, so a real failure is
indistinguishable from a normal agent decision — and with partial observations the run will
confidently answer from incomplete evidence. At minimum log the exception; ideally catch only the
expected parse errors (`json.JSONDecodeError`, `ValueError`, `KeyError`) around the parsing block
and let transport/API errors propagate (or be recorded as a failed observation) instead of
masquerading as a decision.



─── agent_core.py:51-52 ───
[bug · medium] `_env_num` accepts non-finite floats: `AGENT_LOW_RELEVANCE=nan` passes `cast` and the
`value < minimum` guard (`nan < 0.0` is False), so `LOW_RELEVANCE` becomes NaN. Then `top <
LOW_RELEVANCE` in `format_evidence` is always False and the low-confidence warning that the refusal
behaviour depends on is silently disabled (fails open). `inf` is likewise accepted. Reject
non-finite values (e.g. `if isinstance(value, float) and not math.isfinite(value): return default`,
with `import math`), and consider a maximum bound for this threshold since values > 1 make the
warning fire on every search.

+     if isinstance(value, float) and not math.isfinite(value):
+         return default
      if minimum is not None and value < minimum:
          return minimum


─── agent_core.py:191-193 ───
[maintainability · low] The single `try` guards both the tool invocation and all result formatting
(summary f-strings, `c['source'][:14]`, set comprehension). If a formatting/schema bug ever raises
here (e.g. a non-string field making `.strip()`/slicing fail), it is reported to the model as
「工具执行失败」 — a plausible-looking observation that masks the real defect and lets the loop keep running
on corrupted assumptions. Narrow the guarded region to the tool call itself and build the summary
outside the `try`, so genuine code defects surface instead of being laundered into fake tool
failures.



─── agent_core.py:67-68 ───
[bug · low] Check-then-act on the module-level `_client_cache` without synchronization. The
docstrings explicitly target a Streamlit caller, which runs sessions on multiple threads; concurrent
first calls can each construct an `OpenAI` client, and the losing instances (each holding an httpx
connection pool) are dropped without being closed. The impact is minor (duplicate clients/resource
waste, not corruption), but guarding the lazy init with a `threading.Lock` (or initializing under
`functools.cache` with a lock) makes the intent explicit and avoids the wasted pools.




──────── Project Summary ────────

### Top Issues

1. **Vector cache can serve stale or deleted content** — `index_builder.py` validates the cache only by `len(vecs) == len(chunks)` and by "any remaining file newer than cache". In-place edits that preserve chunk count, and file deletions that touch no other file, both pass as "fresh". This silently returns answers grounded in text that no longer exists in the corpus — the highest-impact correctness bug in the repo. Needs a content/manifest-based key (file set + hashes + chunker params), not count/mtime heuristics.

2. **Overly broad `except Exception` converts real failures into plausible-looking output** — same root cause in three places:
   - `answer_generator.py`: the `stream_options` fallback catches auth/rate-limit/network errors and silently re-issues the *same paid request* without `include_usage` (double billing, masked outages).
   - `agent_core.py`: the whole LLM call + JSON parse is wrapped and the exception discarded with no logging, turning outages into a fabricated `answer` decision or forced `search_docs`.
   - `agent_core.py`: one `try` covers both tool invocation and result formatting, so a formatting/schema bug is reported to the model as 「工具执行失败」, sending the agent down the wrong recovery path.

3. **Chunker merges across semantic boundaries, poisoning retrieval** — `chunker.py`: the clause-promotion guard can never fire for intro blocks (`"".split(".")` → `[""]`, length 1), so `clause`/`parent` stay empty after absorbing `14.2.1`; `same_parent` then has no chapter guard and glues an intro chunk to the *next* chapter's clauses. Compounded by per-page state reset in `split_page_by_clause`, clauses continuing across a page break lose their clause identity entirely. Merged chunks carry wrong clause metadata into citations.

4. **Unvalidated numeric parameters cause hangs and silent data loss** — `document_loader.py::chunk_text` with `overlap >= size` yields `step <= 0` and an infinite loop appending duplicates until OOM; `chunker.py`'s `step = max_len - 100` raises `ValueError` at `max_len == 100` and *silently drops the entire paragraph* for `max_len < 100`. Both are caller-supplied values with no guard.

5. **Unguarded dereferences of external API responses** — `answer_generator.py` assumes `resp.choices[0]`, `.message.content`, and `resp.usage.total_tokens` all exist. OpenAI-compatible gateways legitimately return empty `choices`, `content=None` (reasoning/tool-only turns), or `usage=None`. This is the most likely production crash path given the gateway-agnostic design.

6. **Degenerate/empty inputs crash the pipeline** — `index_builder.py`: empty corpus → `np.array([])` shape `(0,)` → `np.linalg.norm(..., axis=1)` raises; `chunker.py`: `total / original_chars` with `original_chars=0` and non-empty chunks → `ZeroDivisionError` (early return only guards empty chunks). Empty corpora are an explicitly reachable state (`load_documents()` returning `[]`), not a theoretical one.

7. **Query rewrite is both contradictory and mis-configured** — `answer_generator.py`: the prompt demands a single verbatim translation in Task/Constraints but three distinct English lines in Output; at `temperature=0` the branch taken is arbitrary. The same call also omits `**chat_extra()`, so `CHAT_DISABLE_THINKING` is not applied — paying 3–4s thinking latency and risking reasoning text leaking into the rewrite.

8. **Ungrounded generation on zero retrieval hits** — `answer_generator.py` calls `generate()` with an empty 资料 section instead of short-circuiting, spending tokens to invite hallucination exactly where the system should refuse.

9. **Non-finite env values silently disable the refusal safety net** — `agent_core.py::_env_num` accepts `nan` (`nan < minimum` is False), so `AGENT_LOW_RELEVANCE=nan` makes `top < LOW_RELEVANCE` always False and the low-confidence warning never fires.

10. **Unsynchronized client cache under Streamlit's threading model** — `agent_core.py` check-then-act on module-level `_client_cache`; concurrent first calls each build an `OpenAI` client and the losers leak httpx connection pools. The docstrings explicitly target the multi-threaded caller.

### Module Hotspots

- **`answer_generator.py` (6 comments)** — highest density: error handling, response-schema assumptions, prompt correctness, config drift, cost control, dead code. This is the LLM boundary and it is the least defensive file in the repo.
- **`chunker.py` (5 comments)** — all correctness/data-integrity: three boundary/state bugs plus two numeric edge cases. Chunk metadata errors propagate into every downstream citation.
- **`agent_core.py` (4 comments)** — error handling, config validation, tool-error attribution, concurrency. Failures here are invisible because they are laundered into normal agent decisions.
- **`index_builder.py` (3 comments)** — concentrated entirely in cache validity and the empty-corpus path.
- `document_loader.py` (1) and the `index_builder.py` ↔ `document_loader.py` chunking seam are lower-volume but share the unvalidated-parameter root cause with `chunker.py`.

### Cross-Cutting Concerns

- **Silent fallback instead of surfaced failure.** Every layer substitutes a plausible default for an error: `answer_generator.py` (retry without usage), `agent_core.py` (fake `answer` decision, misattributed tool failure), `chunker.py` (dropped paragraph), `index_builder.py` (stale cache treated as fresh). No comment reports structured logging on any of these paths — failures are indistinguishable from success in production.
- **No validation at function/config boundaries.** Caller-supplied numerics (`document_loader.py::chunk_text`, `chunker.py` `max_len`/`original_chars`) and env-supplied numerics (`agent_core.py::_env_num`) are trusted. A single shared validation helper would cover all four sites.
- **Empty / zero-length inputs are an unhandled class.** `index_builder.py` (empty corpus, empty `all_vecs`), `chunker.py` (`original_chars=0`, empty clause string), `document_loader.py` (empty `text`), `answer_generator.py` (empty context, empty `choices`). The system has a reachable empty-corpus state that no layer handles end-to-end.
- **Config flags applied inconsistently across call sites.** `chat_extra()` is used in `generate()`/`generate_stream()` but not the rewrite call in `answer_generator.py`; env parsing in `agent_core.py` has its own unvalidated cast. There is no single choke point for LLM request configuration.
- **Single-threaded assumptions in module-level mutable state.** `agent_core.py::_client_cache` is the flagged instance; the same global-cache pattern in `index_builder.py` deserves the same scrutiny given the stated Streamlit deployment.
- **Dead code obscuring intent.** `answer_generator.py` imports `rrf_fuse` (unused; fusion actually goes through `fuse_by_language`) and `search` (only used in a commented-out block in `main()`), making the intended retrieval path ambiguous to readers.

### Quick Wins

- Delete the unused `rrf_fuse` / `search` imports and the commented-out pure-vector block in `answer_generator.py` — removes ambiguity about which fusion path is live.
- Add `**chat_extra()` to the rewrite call in `answer_generator.py` — one-line fix recovering 3–4s per query and stopping reasoning leakage.
- Rewrite the Output section of the rewrite prompt in `answer_generator.py` to match Task/Constraints (pick one: single translation *or* three variants) — removes temperature-0 nondeterminism.
- Short-circuit `generate()` when `build_context()` returns `""` with a fixed 「资料中未找到相关内容」 response — saves tokens and eliminates the least-grounded answer class.
- Guard the divisor in `chunker.py` (`original_chars > 0`, else print `n/a`) and validate `size`/`overlap` in `document_loader.py::chunk_text` and `max_len` in `chunker.py` — a few `if` statements that remove an infinite loop, a `ValueError`, a `ZeroDivisionError`, and silent paragraph loss.
- Add `math.isfinite` to `_env_num` in `agent_core.py` — restores the low-confidence refusal path.
- Narrow the `stream_options` fallback in `answer_generator.py` to the specific rejection error and log everything else; stop re-issuing the paid request on non-`stream_options` failures.
- Split the single `try` in `agent_core.py` so tool invocation and result formatting report distinct errors, and log the swallowed exception in the decision loop.
- Wrap `_client_cache` construction in a `threading.Lock` (double-checked) in `agent_core.py`.
- Reshape/early-return for the empty-corpus case in `index_builder.py` before `np.linalg.norm(..., axis=1)`.
