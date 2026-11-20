# app.py 代码审查报告

> 由 open-code-review 导出，供修改参考。评论原文为英文（模型输出），中文标注为导出时补注。

| 项 | 值 |
|---|---|
| 审查时间 | 2026-11-19 11:47 |
| 模型 | `qwen4-max`（provider:ali） |
| 模式 | full_scan（全文件扫描，非 diff） |
| 文件 | app.py（417 行） |
| 消耗 | 80,046 token（输入 69,936 / 输出 10,110，8 轮调用） |
| 结论 | 5 条（全部 bug 类） |

## 处理优先级

| 优先级 | 位置 | 问题 | 理由 |
|---|---|---|---|
| **P0 立即** | `app.py:397` | `hit` 硬编码 `True`，v1 命中率永远 100% | 一行改动，直接决定检索质量统计是否可信 |
| **P1 建议** | `app.py:262` | 负分被压成 0，同分乱序 | 依赖 `RERANK_MODEL` 取值，换模型会静默劣化排序 |
| P2 可选 | `app.py:203` | `retrieve` 内远程调用无异常处理 | 健壮性，不改变当前正常路径的行为 |
| P2 可选 | `app.py:41` | `RERANK_POOL` 环境变量无校验 | 健壮性，环境变量写错才会触发 |
| P2 可选 | `app.py:57` | `json.loads` 无 try，JSON 损坏即崩 | 健壮性，文件损坏才会触发 |

## 逐条明细

### 1. `app.py:41` — [bug · low]

This runs at import time with no validation: a malformed `RERANK_POOL` env value (e.g. `"20 "` is fine but `"twenty"` or `""` raises ValueError) crashes the app before any UI renders, bypassing the friendly API-key error screen below. Also, nothing guarantees `RERANK_POOL >= top_k` (slider allows up to 10); if an operator sets `RERANK_POOL=5`, enabling rerank silently returns fewer chunks than the user requested. Parse defensively and clamp the pool to at least `top_k` when used.

**现有代码**

```python
RERANK_POOL = int(os.getenv("RERANK_POOL", "20"))
```

**建议改为**

```python
try:
    RERANK_POOL = max(1, int(os.getenv("RERANK_POOL", "20")))
except ValueError:
    RERANK_POOL = 20
```

### 2. `app.py:57` — [bug · low]

`json.loads` here (and the identical pattern in `_load_term_map`) runs at module import with no error handling. The code carefully handles the file-not-exists case, but a malformed/truncated `glossary.json` (or `term_map.json`) raises `JSONDecodeError` at import and takes down the whole app before Streamlit can render anything. Since these are optional enrichment data, catch parse errors and degrade to the empty default (`""` / `{}`), ideally with a warning.

**现有代码**

```python
    terms = json.loads(f.read_text(encoding="utf-8")).get("chapters", [])
```

### 3. `app.py:203` — [bug · medium]

No error handling around any of the remote calls in `retrieve`: the rewrite chat completion, and the embedding calls dispatched via `ex.map` (which re-raises the first worker exception when the results are consumed). A single transient API failure (timeout, rate limit, network blip) propagates out of `retrieve`, aborts the whole request with a raw traceback shown to the user, and skips `log_query` entirely — so failed requests are invisible in the stats. Since `rerank_docs` already degrades gracefully on failure, the retrieval path should too: wrap the rewrite call (fall back to `[question]` on failure) and the parallel retrieval in try/except, and at minimum catch exceptions at the call site to show `st.error` and still log the failed query.

**现有代码**

```python
    queries = rewrite_queries(chat_client, question)
```

### 4. `app.py:262-263` — [bug · medium]

`best.get(i, 0.0)` silently floors any negative cross-encoder score to 0. The rerank model is configurable via `RERANK_MODEL` (see rerank.py), and models that return raw logits can produce negative relevance scores. When that happens, all negative-scoring documents collapse into a tie at 0.0 and `sorted(best.items(), key=lambda x: -x[1])` orders them arbitrarily (dict insertion order), corrupting the ranking instead of placing them last. Use negative infinity as the initial value so real scores always win.

**现有代码**

```python
            for i, s in rerank_docs(rq, docs, top_n=len(docs)):
                best[i] = max(best.get(i, 0.0), s)
```

**建议改为**

```python
            for i, s in rerank_docs(rq, docs, top_n=len(docs)):
                best[i] = max(best.get(i, float("-inf")), s)
```

### 5. `app.py:397-398` — [bug · medium]

The `hit` flag is hardcoded to `True` even when `hits` is empty (e.g. degenerate queries or an empty fusion result), so the logged hit-rate metric for the v1 route is always 100% and useless for evaluating retrieval quality — unlike the agent route, which at least attempts to derive it. Pass `bool(hits)` instead.

**现有代码**

```python
        log_query(question, "v1", "search_docs", answer, elapsed,
                  usage.get("total_tokens"), True, st.session_state.sid)
```

**建议改为**

```python
        log_query(question, "v1", "search_docs", answer, elapsed,
                  usage.get("total_tokens"), bool(hits), st.session_state.sid)
```

---

## 附：模型生成的审查总结（原文）

### Top Issues

1. **Import-time initialization can crash the app before any UI or error screen renders** — `app.py` parses `RERANK_POOL` and calls `json.loads` on `glossary.json` / `_load_term_map`'s `term_map.json` at module scope with no guards. A malformed env value (`"twenty"`, `""`) raises `ValueError`; a truncated JSON file raises `JSONDecodeError`. Both bypass the friendly API-key error screen that the rest of the file deliberately provides. This is one root cause (unguarded module-level side effects) manifesting in three places.

2. **Zero fault tolerance around remote calls in `retrieve`** — `app.py` wraps neither the rewrite chat completion nor the embedding calls dispatched through `ex.map`. Because `ex.map` re-raises the first worker exception when results are consumed, a single transient timeout / rate limit / network blip fails the entire retrieval instead of degrading (e.g. falling back to the un-rewritten query or partial embeddings).

3. **Negative cross-encoder scores are silently floored to 0** — `best.get(i, 0.0)` in `app.py` collapses every negative-scoring document into a single tie bucket. Since `RERANK_MODEL` is configurable (see `rerank.py`) and raw-logit models emit negative relevance, changing one env var silently destroys ranking quality with no error surfaced.

4. **Retrieval-quality telemetry is structurally invalid** — the `hit` flag is hardcoded to `True` in `app.py` even when `hits` is empty (degenerate queries, empty fusion result). The v1 route therefore reports a permanent 100% hit rate, so any regression from issues #2/#3 is invisible in the metrics meant to catch it. The agent route's attempt at real detection makes the inconsistency explicit.

5. **No cross-field config invariant for the rerank pool** — nothing in `app.py` guarantees `RERANK_POOL >= top_k`, so a plausible-looking configuration can truncate the candidate pool below the requested result count and quietly return fewer/degraded results.

### Module Hotspots

- **`app.py`** — 5 of 5 comments, spanning configuration loading, remote-call orchestration, score aggregation, and metrics emission. Severity is concentrated in the module's *initialization and boundary* code rather than its core retrieval logic.
- **`app.py` ↔ `rerank.py` boundary** — the score-flooring bug only manifests for certain `RERANK_MODEL` values, i.e. the coupling between configurable model output range and the consumer's default assumption is undocumented and untested at the seam.
- Note on coverage: all findings come from a single file; the absence of comments elsewhere is not evidence that the rest of the repo is clean.

### Cross-Cutting Concerns

- **Fail-fast at import vs. graceful degradation at runtime.** `app.py` handles the *file-not-exists* case for `glossary.json` / `term_map.json` and renders a friendly API-key screen, yet leaves malformed-content and malformed-env paths unguarded. The error-handling policy is applied to some failure modes and not their obvious siblings.
- **Silent defaults that mask bad or missing data.** `best.get(i, 0.0)` (`app.py`) substitutes a plausible score for absent/negative values; `hit = True` (`app.py`) substitutes a plausible metric for an empty result set. Both convert a detectable failure into an undetectable wrong answer.
- **Unvalidated external configuration.** `RERANK_POOL` (env) and `RERANK_MODEL` (`rerank.py`) are trusted for type, range, and mutual consistency with `top_k`, with no validation layer between configuration and use.

### Quick Wins

- `app.py`: replace `hit = True` with `hit = bool(hits)` — one line, immediately restores a usable hit-rate metric.
- `app.py`: wrap both `json.loads` sites (glossary and `_load_term_map`) in `try/except json.JSONDecodeError`, log a warning, and fall back to an empty map — mirrors the existing file-not-exists handling.
- `app.py`: move `RERANK_POOL` parsing into a validated helper (default on bad input, clamp to `>= top_k`) instead of a bare module-level `int()`.
- `app.py`: change the score default from `0.0` to a sentinel (`None` / `-inf`) or normalize scores per model so negative logits rank correctly; assert the expected score range for the configured `RERANK_MODEL`.
- `app.py`: add a small retry/backoff wrapper around the rewrite completion and the per-item embedding call inside the `ex.map` worker, so one transient failure retries rather than aborting the whole fan-out.
