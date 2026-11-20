
─── tools/hybrid_check.py:37-42 ───
[maintainability · medium] 整段流程（建块、算向量、调用远程 embedding API、跑检索）都写在模块顶层，没有 `if __name__ ==
"__main__":` 保护。任何 `import` 该模块的行为（测试收集、被其它脚本引用）都会立即触发网络请求和费用，且 `show()` 依赖模块级全局
`chunks`，无法复用/测试。建议封装成 `main(chunks)` 并加 `__main__` 守卫，与项目内 `index_builder.py` / `hybrid.py`
的写法保持一致。



─── tools/hybrid_check.py:40-40 ───
[maintainability · medium] `base_url` 被硬编码为硅基流动地址，而 `index_builder` 里实际使用的是可配置的
`EMBED_BASE_URL`（默认同为该地址）。若用户通过 `.env` 切换了 `EMBED_BASE_URL`，本脚本的查询向量仍会打到默认地址，导致与索引构建端不一致或直接鉴权失败。建议复用
`EMBED_BASE_URL`。

-     base_url="https://api.siliconflow.cn/v1",
+     base_url=os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1").strip(),


─── tools/hybrid_check.py:39-39 ───
[bug · medium] 未校验 `SILICONFLOW_API_KEY`：键缺失时默认空串传入客户端，问题要到后续 `embed_query`
请求时才以晦涩的鉴权错误暴露。`index_builder.main()` 对此有显式检查并给出友好提示，本脚本建议沿用同样的前置校验（缺失时 `sys.exit` 明确说明）。

      api_key=os.getenv("SILICONFLOW_API_KEY", "").strip(),
+ )
+ if not os.getenv("SILICONFLOW_API_KEY", "").strip():
+     sys.exit("缺少 SILICONFLOW_API_KEY，请在 .env 中配置后重试")


─── tools/build_equipment_db.py:53-55 ───
[bug · medium] `parse_tension` only recognises limits that carry a weight prefix (`3U ≤31`). The
风刃900 entry uses `tension_raw = "≤32"`, which matches neither regex, so `tension_json` ends up as
`{}` and the parsed data is silently lost — exactly the case the module docstring says must be
stored parsed. Add a fallback that captures a bare `≤ N` limit.

      for w, hi in re.findall(r"([345]U)\s*≤\s*(\d+)", raw or ""):
          out.setdefault(w, [None, int(hi)])
+     if not out:
+         m = re.search(r"≤\s*(\d+)", raw or "")
+         if m:
+             out["default"] = [None, int(m.group(1))]
      return out


─── tools/build_equipment_db.py:157-159 ───
[maintainability · low] `rows` contains the dicts of the module-level `LN` list by reference, so
this loop writes `tension_json` into the shared global data. Calling `main()` a second time (or
importing the module) reuses already-mutated dicts, and the global list no longer matches its
declared schema. Copy the rows before enriching them.

-     rows = from_yonex() + LN
+     rows = from_yonex() + [dict(r) for r in LN]
      for r in rows:
          r["tension_json"] = json.dumps(parse_tension(r["tension_raw"]), ensure_ascii=False)


─── tools/build_term_map.py:58-58 ───
[bug · medium] `os.getenv("CHAT_DISABLE_THINKING")` returns a string, so any non-empty value
(including `false`, `0`, `no`) is truthy and silently disables thinking. This also diverges from the
established pattern in `answer_generator.py`, which parses the same variable with `.strip().lower()
in ("1", "true", "yes")`. Parse the flag once at module level with the same semantics.

Suggested: add near the other env reads
```python
DISABLE_THINKING = os.getenv("CHAT_DISABLE_THINKING", "").strip().lower() in ("1", "true", "yes")
```
then spread kwargs instead of passing `extra_body=None`.



─── tools/build_term_map.py:63-65 ───
[bug · medium] LLM output is only checked for JSON syntax, not for the expected shape. If the model
returns a top-level array (or a dict whose values are plain strings instead of lists), `json.loads`
succeeds but `mapping.items()`/`for zh in zhs` either raises `AttributeError` or silently iterates
the string character by character, corrupting `term_map.json` with one-char keys. Validate structure
before building `reverse` and fail with the same raw-output diagnostics used for the JSON error
path.

  try:
      mapping = json.loads(raw)
  except json.JSONDecodeError:
+     print("解析失败，原始输出：")
+     print(raw[:800])
+     raise SystemExit(1)
+ 
+ if not isinstance(mapping, dict) or not all(isinstance(v, list) for v in mapping.values()):
+     print("返回结构不符合预期，原始输出：")
+     print(raw[:800])
+     raise SystemExit(1)


─── tools/build_term_map.py:25-25 ───
[maintainability · medium] Unlike `examples/minimal_demo.py` / `answer_generator.py`, there is no
fail-fast check on the required env vars. With `DEEPSEEK_BASE_URL` or `DEEPSEEK_MODEL` unset,
`OpenAI(base_url="", ...)` is constructed successfully and the failure only surfaces later as an
opaque httpx/auth/400 error from `client.chat.completions.create`. Validate the config (or at least
non-empty `CHAT_KEY`/`CHAT_BASE_URL`/`CHAT_MODEL`) right after reading it, before building the
client.



─── tools/build_term_map.py:29-29 ───
[maintainability · low] `"CLOTHING REGULATIONS FOR UMPIRES WHERE A UNIF"` does not match any entry
in `tools/glossary.json` (the actual chapter list has no such title, and the string looks truncated
mid-word). This skip entry is dead data and gives a false sense that the chapter is filtered; remove
it or replace it with the exact glossary title.



─── tools/eval_80.py:131-132 ───
[bug · medium] `app.retrieve()` can legitimately return an empty hit list (see app.py:270, which
returns `fused[:top_k]`, and also the rerank fallthrough at app.py:266-270). Indexing `hits[0]`
directly would then raise `IndexError` and abort the whole evaluation run mid-way, losing the
remaining groups. Guard the empty case and treat it as a miss.

          _, hits = app.retrieve(q, 5)
+         if not hits:
+             low.append((code, q, 0.0))
+             print(f"  [LOW ] {code:<5}{0.0:<7.3f}{q[:30]:<32}{'(no hits)'}", flush=True)
+             continue
          s, c = hits[0]


─── tools/eval_80.py:129-129 ───
[maintainability · low] `low` is written (`low.append(...)`) but never read anywhere afterwards —
the LOW cases are already printed inline, so this list is dead state. Either drop it, or actually
use it (e.g. print the per-group low-score list at the end of the group) to match the docstring's
“低分的会单独列出待查”.



─── tools/eval_80.py:27-27 ───
[bug · medium] Refusal detection relies on bare substring matches of very generic fragments: `没有`
already subsumes `没有提到`/`资料中没`, and it also matches legitimate partial answers such as “规则里没有统一规定”.
Conversely, valid refusals phrased differently (“抱歉，我不清楚” / “该问题超出资料范围”) are not in the list and get
scored as fabrications, skewing the “拒答正确率” metric. Consider matching a smaller set of distinctive
refusal markers and/or requiring the marker plus a short answer, instead of one-word substring
checks.



─── tools/trace_pipeline.py:6-7 ───
[maintainability · low] `json` is imported but never used anywhere in this script (no `json.`
reference below). Unused import should be removed to keep the trace tool clean.

- import json
  import os


─── tools/trace_pipeline.py:75-76 ───
[bug · medium] Step 5 does not reproduce the real rerank stage: `app.retrieve` reranks with **two**
queries (`[question] + queries[:1]`, taking the per-chunk max, see app.py:259-264) and passes
`top_n=len(docs)`. Tracing with only the Chinese query (and `top_n=POOL`) can produce a different
ordering than the actual pipeline, so the printed "重排后" list may not match what step 6 / production
returns — which defeats the purpose of a trace tool. Also note `rerank()` swallows all errors and
returns `[]`, so with `top_n=POOL > len(cand)` (or a missing SILICONFLOW_API_KEY) this block
silently prints nothing instead of signaling failure.

- ranked = rerank(Q, [app.chunks[i]["text"] for i in cand], top_n=POOL)
+ docs = [app.chunks[i]["text"] for i in cand]
+ best: dict[int, float] = {}
+ for rq in [Q] + list(queries[:1]):
+     for i, s in rerank(rq, docs, top_n=len(docs)):
+         best[i] = max(best.get(i, 0.0), s)
+ ranked = sorted(best.items(), key=lambda x: -x[1])
+ if not ranked:
+     print("  重排未返回结果（API 失败或缺少 Key），回退到融合顺序")
  print(f"  重排后前 6：")


─── tools/diagnose_retrieval_fail.py:32-32 ───
[bug · medium] 缓存文件名写死为 `chunks_v2.json`，但上面用的是 `os.environ.setdefault("RAG_TAG", "v2")`——若外部环境已设置
`RAG_TAG=v1` 之类，`import app` 会加载 `chunks_{TAG}.json`，而这里的 `cs` 仍读 v2 的缓存。此时第 1 步打印的「答案块号」来自另一套语料，第 5
步用 `cs.index(...)` 与 `app.chunks.index(...)` 比较块号也失去意义，诊断结论会是错的。建议直接复用 app 已按 RAG_TAG 加载好的块列表。

- cs = json.loads((ROOT / "chunks_v2.json").read_text(encoding="utf-8"))
+ # 复用 app 已按 RAG_TAG 加载的块列表，避免与 app 使用的缓存文件不一致
+ cs = app.chunks


─── tools/diagnose_retrieval_fail.py:35-36 ───
[bug · medium] 用 `cs.index(c)` / `app.chunks.index(c)` 按「值相等」反查块号并不可靠：`list.index`
返回第一个相等的元素，若语料中存在内容完全相同的重复块（同一段文字被切进多个块的情况很常见），打印的 `#idx` 和最终 `是否命中`
都会指向错误的块号（重复块会被折叠成同一个下标）。建议在遍历时用 `enumerate` 直接保留下标，让 `found` 携带块号。

- for c in found:
-     idx = cs.index(c)
+ for idx, c in enumerate(cs):
+     if "change ends" in c["text"].lower() or "change of ends" in c["text"].lower():



──────── Project Summary ────────

# Project Summary — Full-Repo Scan

Scope of this pass is narrow but consistent: all 16 comments land in **`tools/`** (6 scripts). No comments surfaced outside `tools/`, which itself is a signal — the diagnostic/ingest helper scripts appear to be the least-reviewed and least-owned layer of the repo.

### Top Issues

1. **Diagnostic tooling re-implements the pipeline and silently diverges from `app.py`.** Three separate scripts duplicate retrieval logic and then drift from the real implementation, so their output can mislead debugging:
   - `tools/trace_pipeline.py` Step 5 reranks with a single query and `top_n=POOL`, while `app.retrieve` uses two queries (`[question] + queries[:1]`, per-chunk max, `top_n=len(docs)`, `app.py:259-264`) — traced orderings won't match runtime.
   - `tools/hybrid_check.py` hardcodes the SiliconFlow `base_url` instead of the configurable `EMBED_BASE_URL` used by `index_builder`, so a `.env` override puts query and index vectors on different endpoints.
   - `tools/diagnose_retrieval_fail.py` hardcodes `chunks_v2.json` while `import app` honors `RAG_TAG` — a `RAG_TAG=v1` environment makes the printed block numbers refer to a different corpus than the one actually queried.
   Root cause is the same everywhere: each tool rebuilds the pipeline by hand rather than importing a shared helper. This is the highest-impact class because these tools exist specifically to produce trustworthy answers during incidents.

2. **Module-level side effects make `tools/` unsafe to import or re-run.**
   - `tools/hybrid_check.py` performs chunking, embedding, paid remote API calls and retrieval at module top level with no `if __name__ == "__main__":` — any import (test collection, cross-script use) triggers network traffic and cost.
   - `tools/build_equipment_db.py` writes `tension_json` into dicts held **by reference** in the module-level `LN` list, so a second `main()` call (or import) operates on already-mutated globals that no longer match their declared schema.

3. **Env/config handling is duplicated, inconsistent, and not fail-fast.** Config reads diverge from the established pattern in `answer_generator.py`:
   - `tools/build_term_map.py` parses `CHAT_DISABLE_THINKING` via bare truthiness, so `false`/`0`/`no` silently disable thinking (differs from `.strip().lower() in (...)` in `answer_generator.py`).
   - Same file has no upfront check for `DEEPSEEK_BASE_URL`/`DEEPSEEK_MODEL`; `OpenAI(base_url="", ...)` succeeds and fails later as an opaque httpx/auth error, unlike `index_builder.main()` which checks explicitly.
   - `tools/hybrid_check.py` never validates `SILICONFLOW_API_KEY`, passing an empty string until `embed_query` fails obscurely.
   A single shared config/bootstrap helper would eliminate this whole class.

4. **Silent data loss in DB generation.** `tools/build_equipment_db.py:parse_tension` only matches weight-prefixed limits (`3U ≤31`); the 风刃900 entry `≤32` matches neither regex and becomes `{}` with no warning — a direct violation of the module docstring's contract and a data-quality hole in the generated equipment DB.

5. **LLM output is syntax-checked but not shape-checked.** `tools/build_term_map.py` accepts any valid JSON; a top-level array or string-valued dict either raises `AttributeError` on `.items()` or silently iterates characters of a string. Fail-fast schema validation is missing.

6. **`tools/eval_80.py` aborts the whole evaluation on a legitimate empty result.** `app.retrieve()` returns `fused[:top_k]` and can be empty (`app.py:266-270`); `hits[0]` then raises `IndexError` and discards all remaining evaluation cases. Compounded by substring-based refusal detection (`没有`, `没有提到`, `资料中没`) that over-matches partial answers like "规则里没有统一规定" while missing differently-worded refusals — the reported metrics are both fragile and inaccurate.

### Module Hotspots

- **`tools/`** — 100% of comments. Every file examined has 2–4 findings; there are no clean files in this directory.
- Densest sub-hotspots: `tools/build_term_map.py` (4), `tools/hybrid_check.py` (3), `tools/eval_80.py` (3). These three also carry the highest-severity items (fail-fast config, paid side effects on import, run-aborting crash).

### Cross-Cutting Concerns

- **Pipeline logic duplicated instead of shared** — `tools/trace_pipeline.py`, `tools/hybrid_check.py`, `tools/diagnose_retrieval_fail.py`, `tools/eval_80.py` all re-derive retrieval/rerank/cache behavior; drift is systemic, not incidental.
- **Weak input/output validation** — `tools/build_equipment_db.py` (`parse_tension`), `tools/build_term_map.py` (LLM shape), `tools/eval_80.py` (refusal heuristic). Missing/brittle parsing converts errors into silent wrong data rather than loud failures.
- **Non-idempotent / import-unsafe scripts** — `tools/hybrid_check.py` (top-level network work), `tools/build_equipment_db.py` (shared mutable globals via `LN` reference).
- **Config/env divergence from the app layer** — `tools/build_term_map.py`, `tools/hybrid_check.py` versus the established `answer_generator.py` / `index_builder.py` conventions.
- **Dead code / dead data** — `tools/trace_pipeline.py` (unused `json` import), `tools/eval_80.py` (unused `low` list), `tools/build_term_map.py` (orphaned skip entry whose title doesn't exist in `tools/glossary.json` and looks truncated mid-word).

### Quick Wins

- Wrap `tools/hybrid_check.py` execution in `if __name__ == "__main__":`; import `EMBED_BASE_URL` from `index_builder` instead of hardcoding `base_url`; add the same API-key precondition check `index_builder.main()` already has.
- In `tools/build_term_map.py`: replace the `CHAT_DISABLE_THINKING` parse with the `.strip().lower()` logic copied from `answer_generator.py`; add a `DEEPSEEK_BASE_URL`/`DEEPSEEK_MODEL` fail-fast; reject non-dict-of-lists JSON before use; delete the dead skip entry.
- `tools/eval_80.py`: guard `hits[0]` (skip or print-and-continue) and either use or remove the `low` list; tighten the refusal matcher to require more specific phrases.
- `tools/trace_pipeline.py`: remove the unused `json` import.
- `tools/build_equipment_db.py`: extend `parse_tension` to accept bare `≤NN`, and `copy.deepcopy` rows before writing `tension_json` so `main()` is idempotent.
- `tools/diagnose_retrieval_fail.py`: derive the cache filename from `RAG_TAG` and replace `list.index(...)` lookups with `enumerate` to survive duplicate chunks.
