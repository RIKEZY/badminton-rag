
─── tools/api_check.py:32-32 ───
[security · high] Printing part of the API key to stdout leaks a secret: when this script runs in CI
or its output is pasted into an issue/chat, `DEEPSEEK_API_KEY` is partially exposed. Also note that
for keys shorter than 12 chars `api_key[:8]` and `api_key[-4:]` overlap and print the *entire* key.
Log only the length (or a stable hash) instead of any key characters.

- print(f"key      : {api_key[:8]}...{api_key[-4:]}  (长度 {len(api_key)})")
+ print(f"key      : *** (长度 {len(api_key)})")


─── tools/api_check.py:15-15 ───
[maintainability · low] The script only uses stdlib + dotenv and never imports any project module,
so this `sys.path` bootstrap (and its explanatory comment) is dead code. Remove it — and then the
`Path` import becomes unused as well.



─── tools/api_check.py:8-8 ───
[documentation · low] The docstring tells the reader to run `python test_api.py`, but the file is
`tools/api_check.py`. Following the documented command will fail with "No such file". Update the run
instruction to match the actual path.

-     python test_api.py
+     python tools/api_check.py


─── tools/api_check.py:26-26 ───
[bug · medium] Required env vars are read with empty-string defaults and never validated. If
`DEEPSEEK_BASE_URL` is unset, the request URL degrades to `/chat/completions`, and `urlopen` raises
a `ValueError: unknown url type` that the generic `except Exception` only prints as `ValueError:
...`, which is confusing for a diagnostic script. Fail fast with an explicit message when
`base_url`/`model`/`api_key` are missing.

  base_url = os.getenv("DEEPSEEK_BASE_URL", "").strip().rstrip("/")
+ if not base_url or not api_key or not model:
+     sys.exit("缺少环境变量：请设置 DEEPSEEK_BASE_URL / DEEPSEEK_API_KEY / DEEPSEEK_MODEL")


─── tools/build_eval_v2.py:7-7 ───
[maintainability · medium] The corpus path is resolved relative to the current working directory, so
running this script from anywhere other than the repo root raises `FileNotFoundError`. Other tools
in this repo (e.g. `tools/recheck_gaps.py`, `tools/diagnose_retrieval_fail.py`) consistently anchor
the file via `ROOT = Path(__file__).resolve().parent.parent`. The file handle is also left to GC
cleanup instead of being closed explicitly.

- cs = json.load(open("chunks_v2.json", encoding="utf-8"))
+ from pathlib import Path
+ 
+ ROOT = Path(__file__).resolve().parent.parent
+ with (ROOT / "chunks_v2.json").open(encoding="utf-8") as f:
+     cs = json.load(f)


─── tools/build_eval_v2.py:33-33 ───
[performance · low] `kw.lower()` is invariant across the whole chunk list but is recomputed for
every chunk of every candidate (the corpus is scanned once per question). Hoisting it out of the
comprehension avoids redundant allocations on a full-corpus scan.

-     hits = [c for c in cs if c["source"] == src and kw.lower() in c["text"].lower()]
+     kw_lower = kw.lower()
+     hits = [c for c in cs if c["source"] == src and kw_lower in c["text"].lower()]


─── tools/build_eval_v2.py:14-14 ───
[other · low] A bare numeric keyword like `"5.17"` makes this validation check unreliable: it also
matches unrelated occurrences (e.g. `15.17`, version numbers, other clause references), so the
script can report `OK` even though the answer to “how may the umpire deal with misconduct” is not
actually present in a usable form. Same concern applies to `"52"` for the ranking-period question.
Prefer a distinctive phrase from the clause (e.g. the misconduct wording of clause 5.17) so the hit
really proves the answer block exists.



─── tools/bm25_check.py:24-24 ───
[bug · medium] 加载缓存时没有任何兜底：缓存不存在会直接抛 FileNotFoundError（栈里看不出是缓存没生成）；更隐蔽的是缓存为空列表时，`BM25Okapi([])`
内部会执行 `sum(doc_len) / corpus_size`（corpus_size=0）而抛
ZeroDivisionError，报错信息与本脚本要验证的「索引是否通」完全无关，排查成本高。建议在读缓存前校验存在性与非空。

+ if not CHUNK_CACHE.exists():
+     sys.exit(f"找不到 {CHUNK_CACHE}，请先运行 python index_builder.py 生成切块缓存")
+ 
  chunks = json.loads(CHUNK_CACHE.read_text(encoding="utf-8"))
+ if not chunks:
+     sys.exit(f"{CHUNK_CACHE.name} 中没有块，请先重建索引")


─── tools/bm25_check.py:42-42 ───
[test · low] 脚本自称「冒烟测试」，但全程只 print，既没有断言也没有非零退出码：即使 BM25 完全失效（例如 Rally 定义的块掉出 top5），脚本仍以 0 退出，无法接入
CI 或作为构建前置检查自动判定失败。建议对 top-N 结果做一次断言，失败时 sys.exit(1)。

+ if not any("rally" in chunks[idx]["text"].lower() for idx in order[:5]):
+     sys.exit("BM25 冒烟测试失败：top5 中不含 Rally 相关块")
+ 
  for rank, idx in enumerate(order[:5], 1):


─── experiments/v2_planner.py:81-82 ───
[bug · medium] LLM output is only checked for JSON syntax, not for the expected shape. If the model
returns `{"needs": "球拍规格限制"}` (a plain string instead of a list), the comprehension iterates the
string character by character and `split_needs` returns one bogus need per character; if it returns
`{"needs": [null]}`, `str(None)` turns it into the literal need `"None"`. Both cases silently
produce garbage retrieval queries instead of falling back to the single-need path. Validate that the
parsed payload is a dict whose `needs` is a list of non-empty strings before using it.

-         needs = json.loads(raw).get("needs") or []
-         needs = [str(n).strip() for n in needs if str(n).strip()]
+         parsed = json.loads(raw)
+         needs = parsed.get("needs") if isinstance(parsed, dict) else None
+         if not isinstance(needs, list):
+             needs = []
+         needs = [n.strip() for n in needs if isinstance(n, str) and n.strip()]


─── experiments/v2_planner.py:83-83 ───
[maintainability · low] `except Exception` silently swallows every failure in the parsing block,
including programming errors such as `AttributeError` from an unexpected JSON shape or a `TypeError`
inside the comprehension, and leaves no diagnostic. Narrow it to the exceptions actually expected
here (`json.JSONDecodeError`, plus `AttributeError` if the dict check above is omitted) and log the
offending raw output to stderr so a degraded run is at least observable.

-     except Exception:
+     except (json.JSONDecodeError, AttributeError) as err:
+         print(f"[warn] 拆解输出解析失败：{err}；raw={raw[:200]!r}", file=sys.stderr)


─── experiments/v2_planner.py:32-32 ───
[maintainability · medium] No fail-fast check on the required config. `OpenAI(api_key="",
base_url="")` constructs successfully, so with `.env` unset the failure only surfaces later inside
`client.chat.completions.create(...)` as an opaque httpx/auth error (cf. `answer_generator.py` /
`examples/minimal_demo.py`, which validate the env vars up front). Validate `CHAT_KEY` /
`CHAT_BASE_URL` / `CHAT_MODEL` right after reading them — preferably inside `split_needs` (or a lazy
client accessor) so importing this module does not raise.

- client = OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)
+ def _get_client() -> OpenAI:
+     if not (CHAT_KEY and CHAT_BASE_URL and CHAT_MODEL):
+         raise RuntimeError(
+             "缺少配置：DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL 都必须非空"
+         )
+     return OpenAI(api_key=CHAT_KEY, base_url=CHAT_BASE_URL)
+ 
+ 
+ client = _get_client()


─── experiments/v2_regression.py:33-33 ───
[bug · medium] This local is_hit deviates from the official criterion in run_eval.is_hit, which
matches on `abs(c["page"] - page) <= 1` and compares the keyword case-insensitively
(`keyword.lower() in text_lower`). Using exact page equality and case-sensitive `kw in c["text"]`
makes this regression script stricter than the baseline it is supposed to compare against, so it can
report false MISS and a non-comparable Recall@5. Align the matching logic with run_eval.

-             if c["source"] == src and c["page"] == page and kw in c["text"]:
+             if (c["source"] == src
+                     and abs(c["page"] - page) <= 1
+                     and kw.lower() in c["text"].lower()):


─── experiments/v2_regression.py:17-17 ───
[bug · low] The corpus path is built from `os.path.dirname(__file__)`, which is relative whenever
the script is invoked via a relative path (e.g. `python experiments/v2_regression.py`). It then
resolves against the current working directory, so running from a different cwd silently points
RAG_DATA_DIR at the wrong/empty corpus — exactly the failure this check is meant to prevent. Use a
resolved absolute path (consistent with `_ROOT` above).

- os.environ.setdefault("RAG_DATA_DIR", os.path.join(os.path.dirname(__file__), "data_rules_only"))
+ os.environ.setdefault("RAG_DATA_DIR", str(Path(__file__).resolve().parent / "data_rules_only"))


─── tools/compare_rerank.py:53-54 ───
[maintainability · medium] The average is divided by a literal `3`, while the loop above uses
`range(3)`. These two numbers must stay in sync manually; if the iteration count is ever changed
(e.g. to 5), the divisor silently stays at 3 and every "average" is wrong without any error. Derive
the denominator from `len(runs)` (and ideally define a single `N_RUNS` constant used by both the
loop and the divisor).

- avg_old = sum(r[0] for r in runs) / 3
- avg_new = sum(r[1] for r in runs) / 3
+ avg_old = sum(r[0] for r in runs) / len(runs)
+ avg_new = sum(r[1] for r in runs) / len(runs)


─── tools/chunk_quality.py:6-6 ───
[documentation · medium] The run instruction points to `test_chunker.py`, but this file is
`chunk_quality.py` (no `test_chunker.py` exists in the repo). Anyone following the docstring will
hit "can't open file". Update the command to `.venv/Scripts/python.exe tools/chunk_quality.py`.

-     .venv/Scripts/python.exe test_chunker.py
+     .venv/Scripts/python.exe tools/chunk_quality.py


─── tools/chunk_quality.py:18-19 ───
[maintainability · low] The whole pipeline (PDF parsing, chunking, printing) runs at module import
time because there is no `if __name__ == "__main__":` guard. Any accidental import of this module —
e.g. a future test or tool that does `from chunk_quality import ...` — will re-run the PDF
extraction and print output as a side effect. Wrap the body in a `main()` function and call it under
the `__main__` guard. Also worth handling the case where the hard-coded `badminton_rules.pdf` is
missing (a bare `FileNotFoundError` traceback is unhelpful for a diagnostics script).



─── experiments/v2_retrieve.py:39-39 ───
[performance · medium] 每个需求都会跑一次完整的 v1 流水线（`rewrite_queries` 一次 LLM 调用 + 九路检索 + 可能的 cross-encoder
重排，单次约数秒），这里是串行调用，拆出 N 个需求时耗时近似 N 倍。`retrieve` 只读取 `chat_client` / `embed_client` / `chunks` /
`vecs` / `bm25` 等只读全局，app.py 内部本身也是用 ThreadPoolExecutor 并发跑的，所以这里同样可以并发调用并保持顺序。另外建议先去重需求（LLM
偶尔会返回重复需求），避免重复跑整条流水线。

-     per_need_hits = [retrieve(n, per_need)[1] for n in needs]
+     unique_needs = list(dict.fromkeys(needs))
+     with ThreadPoolExecutor(max_workers=len(unique_needs)) as ex:
+         per_need_hits = list(ex.map(lambda n: retrieve(n, per_need)[1], unique_needs))


─── experiments/v2_retrieve.py:74-74 ───
[maintainability · low] 解包出来的 `score` 在本循环里从未使用（打印只用 `c`），属于无用变量，建议用 `_` 占位，避免误以为分数被展示/使用。

-         for pos, (score, c) in enumerate(hits, 1):
+         for pos, (_, c) in enumerate(hits, 1):


─── tools/check_stability.py:30-30 ───
[bug · medium] `app.chunks.index(c)` 依赖 `list.index` 的 `==` 语义：当语料里存在两个内容完全相同的块 dict
时，返回的是**第一个**相等元素的下标，而不是真正命中的那一个，从而把 `hit` 判定弄错（这直接影响本脚本「是否命中答案块」的结论）；此外块不存在时还会抛
`ValueError`。建议按对象身份建一次索引表再查。

-     idxs = [app.chunks.index(c) for _, c in hits]
+     idxs = [IDX[id(c)] for _, c in hits]


─── tools/check_stability.py:23-23 ───
[maintainability · medium] `TARGET` 是硬编码的块下标，强依赖于当前语料（`data_rules_only` 的切块顺序）。一旦语料或切块逻辑变化（index 越界
/ 该位置不再是换边规则），`hit` 恒为「无」，脚本会把这个假阴性误读成「检索结果不稳定」。建议在跑检索前先校验下标与内容。

  TARGET = [18, 460]          # 含换边规则的块


─── tools/check_stability.py:12-13 ───
[maintainability · low] 这里用 `setdefault` 设置 `RAG_TAG` / `RAG_DATA_DIR`，意味着 shell
里已导出的同名环境变量会优先生效（且下面 `load_dotenv()` 默认也不覆盖已存在的值），于是脚本可能实际跑在**另一份语料**上，而 `TARGET` 的下标是按
`data_rules_only` 定的，结论会静默失真。既然本脚本的结论依赖固定语料，建议像下一行 `RAG_RERANK` 一样直接赋值强制覆盖。

- os.environ.setdefault("RAG_TAG", "v2")
- os.environ.setdefault("RAG_DATA_DIR", str(ROOT / "data_rules_only"))
+ os.environ["RAG_TAG"] = "v2"
+ os.environ["RAG_DATA_DIR"] = str(ROOT / "data_rules_only")


─── tools/backup_log.py:23-24 ───
[bug · medium] The backup is written directly to the final file name, and the name has only day
granularity. Two consequences:

1. If the run is interrupted (disk full, OOM, SIGKILL, cron timeout), a truncated or 0-byte
`query_log-YYYYMMDD.db` stays in `DST_DIR`. Since the cleanup keeps files for `KEEP_DAYS` based on
mtime, that bogus file survives for a month and is indistinguishable from a good backup — exactly
the failure mode this script is meant to avoid.
2. A second run on the same day opens the existing file as the backup target instead of failing or
starting fresh (`sqlite3.connect(dst)` on an existing/partial DB), so the earlier good backup for
that day is silently replaced.

Write into a temp file in the same directory and `os.replace()` it into place only after `backup()`
returns, so an interrupted run leaves no file under the backup name.

- with sqlite3.connect(SRC) as src, sqlite3.connect(dst) as out:
+ tmp = dst.with_name(dst.name + ".tmp")
+ tmp.unlink(missing_ok=True)
+ try:
+     with sqlite3.connect(SRC) as src, sqlite3.connect(tmp) as out:
-     src.backup(out)
+         src.backup(out)
+     os.replace(tmp, dst)  # 备份成功后才落到正式文件名
+ finally:
+     tmp.unlink(missing_ok=True)


─── tools/backup_log.py:15-15 ───
[bug · low] `int(...)` is applied without validation: a non-numeric/empty
`QUERY_LOG_BACKUP_KEEP_DAYS` raises a bare `ValueError` at import time (before the friendly
`SystemExit` below), and a value of `0` or a negative one makes the cleanup loop delete the backup
that was just created (its mtime is older than the cutoff computed afterwards). The script would
then still print “已备份 …，当前共 0 份”, i.e. silently leave no backups at all. Parse defensively and clamp
to at least 1 day.

- KEEP_DAYS = int(os.getenv("QUERY_LOG_BACKUP_KEEP_DAYS", "30"))
+ try:
+     KEEP_DAYS = max(1, int(os.getenv("QUERY_LOG_BACKUP_KEEP_DAYS", "30")))
+ except ValueError:
+     raise SystemExit("QUERY_LOG_BACKUP_KEEP_DAYS 必须是整数")


─── tools/compare_sql_vs_rag.py:24-24 ───
[maintainability · low] This whole comparison runs at module import time: importing `app` (which
boots the Streamlit app and loads the vector index) plus per-question `app.retrieve` /
`app.generate` calls (LLM + embedding API calls) all execute on import. If this module is ever
imported (test collection, an IDE, another tool), it will silently trigger the full pipeline and
incur API cost. Other tool scripts in this repo (e.g. `tools/equipment_query.py`) guard their
executable code with `if __name__ == "__main__":`. Wrap the loop (and ideally the `import app` side
effects) in a `main()` invoked under that guard.

+ def main():
- for q, model in QS:
+     for q, model in QS:


─── tools/eval_new.py:58-58 ───
[bug · medium] `hits` can legitimately be empty: `app.retrieve` returns `fused[:top_k]` (or the
rerank fallback) and `fuse_by_language` can yield no results, in which case `hits[0][1]` raises
IndexError and aborts the entire evaluation. `is_hit` already tolerates empty `hits`, so guard the
`top1` formatting to match.

+         if hits:
-         top = f"{hits[0][1]['source'][:16]} p{hits[0][1]['page']}"
+             top = f"{hits[0][1]['source'][:16]} p{hits[0][1]['page']}"
+         else:
+             top = "(no hits)"


─── tools/compare_term_strategy.py:14-15 ───
[bug · medium] `RAG_TAG` / `RAG_DATA_DIR` are set with `setdefault`, so a stale value exported in
the shell (e.g. a leftover `RAG_TAG=rules`) is honored. `index_builder` reads `RAG_TAG` at import
time and would then load `chunks_rules.json` (the old ~82-chunk corpus) instead of `chunks_v2.json`,
which makes every hardcoded id in `CASES` (`18`, `460`, `27`, `469`, `397`) point at unrelated
blocks — the script would keep printing ✅/❌ against a different corpus without any error.
`tests/conftest.py` guards against exactly this trap by assigning instead of `setdefault`.

- os.environ.setdefault("RAG_TAG", "v2")
- os.environ.setdefault("RAG_DATA_DIR", str(ROOT / "data_rules_only"))
+ os.environ["RAG_TAG"] = "v2"
+ os.environ["RAG_DATA_DIR"] = str(ROOT / "data_rules_only")


─── tools/compare_term_strategy.py:46-46 ───
[bug · low] The `✅` / `❌` glyphs are not encodable in a GBK/cp936 console (common on Windows, where
the rest of the Chinese output renders fine but emoji raise `UnicodeEncodeError`). Since no other
script in the repo prints emoji, this run would abort partway through the comparison. Consider plain
ASCII markers such as `HIT` / `MISS`.

-         print(f"       BM25 top5={idxs}  {'✅' + str(ok) if ok else '❌'}")
+         print(f"       BM25 top5={idxs}  {'HIT' + str(ok) if ok else 'MISS'}")


─── tools/eval_expanded.py:11-11 ───
[maintainability · low] `re` is imported but never used anywhere in this script (no `re.` call in
the body). Unused import — dead code, please drop it.



─── tools/eval_expanded.py:103-103 ───
[bug · medium] `hits[0]` is indexed without checking that `retrieve()` returned anything.
`app.retrieve` returns `(queries, fused[:top_k])`, which is an empty list when nothing is retrieved
(e.g. empty/failed index or empty fusion result). A single empty result then raises `IndexError` and
aborts the whole eval run instead of just marking that question MISS. Guard the empty list before
formatting `top`.

-         top = f"{hits[0][1]['source'][:18]}p{hits[0][1]['page']}"
+         top = (f"{hits[0][1]['source'][:18]}p{hits[0][1]['page']}" if hits else "-")


─── tools/eval_expanded.py:126-126 ───
[bug · medium] Two problems on this line: (1) `top_c` is unpacked but never used — dead code, since
only `top_score` is printed; (2) `hits[0]` is unguarded — for exactly this group of "known gap"
questions the retriever may legitimately return an empty list, and unpacking `hits[0]` would then
crash with `IndexError`/`ValueError` and take down the report. Use `.get`-style fallback or skip
empty results.

-         top_score, top_c = hits[0]
+         if not hits:
+             print(f"  [{reason:<5}] 无检索结果      {q[:26]:<28}{note}")
+             continue
+         top_score = hits[0][0]


─── tools/eval_expanded.py:80-80 ───
[test · medium] These markers are too broad to detect a refusal and will inflate the negative-sample
score. `agent_core.run` returns the literal refusal text `f"资料中没有检索到相关内容{done}。"` when no evidence
is gathered, but a hallucinated answer can easily contain `没有` / `无法` / `不知道` (e.g. "林丹没有参加 2028
年奥运会，他已拿过 5 次世锦赛冠军"), which would be scored as a correct refusal. Match the actual refusal sentence
(or its stable prefix / trailing `。` form) instead of generic negation words.

- REFUSE_MARKERS = ("没有", "未收录", "不知道", "无法", "资料中没", "没有提到")
+ REFUSE_MARKERS = ("资料中没有检索到相关内容",)


─── tools/extract_glossary.py:36-37 ───
[bug · high] The manual check is broken for at least two entries: the extracted titles in this repo
are `CONTINUOUS PLAY, MISCONDUCT & PENALTIES` (not `CONTINUOUS PLAY, MISCONDUCT`) and there is no
numbered chapter named `INTERVAL` (the source has a lowercase, un-numbered `Intervals:` sub-heading
in Law 16). So the ✅/❌ output permanently shows ❌ for genuinely present concepts, which makes the
verification untrustworthy. Also, the result is only printed — the script never exits non-zero, so a
failed check can never fail a build. Suggest matching by substring on the real titles and failing
the script on a miss.

+ MUST_HAVE = [
+     "CHANGE OF ENDS", "INTERVALS", "SERVICE", "SCORING SYSTEM", "FAULTS", "LETS",
+     ...
+ ]
+ 
+ missing = [t for t in MUST_HAVE if not any(t in c for c in chapters)]
  for t in MUST_HAVE:
-     print(f"  {'✅' if t in chapters else '❌'}  {t}")
+     print(f"  {'✅' if t not in missing else '❌'}  {t}")
+ if not chapters:
+     sys.exit("no chapters extracted")
+ if missing:
+     sys.exit(f"missing required terms: {missing}")


─── tools/extract_glossary.py:19-20 ───
[bug · medium] If `data_rules_only/` is missing or empty (e.g. the data isn't checked out, or the
script is run from a different layout), `glob` silently yields nothing: the script prints `从原文提取 0
个章节标题` and then overwrites `tools/glossary.json` with an empty chapter list, destroying the previous
good output without any error. Guard against an empty input set (and ideally against a missing
`DATA` dir) before writing the result.

+ if not DATA.is_dir():
+     sys.exit(f"input directory not found: {DATA}")
+ 
  chapters = Counter()
  for f in DATA.glob("*.txt"):


─── tools/extract_glossary.py:24-24 ───
[bug · low] The extraction quietly drops any heading the regex can't capture: titles longer than 52
characters, and titles containing characters outside `[A-Z0-9 ,'\-&]` (parentheses, `:`, `/`,
lowercase) never match `CHAPTER` and are lost with no warning. Several captured titles are already
50+ chars, so this limit is close to biting. Consider loosening the character class/length bound and
logging the lines that look like headings but were skipped, so gaps are visible instead of silent.



─── tools/fetch_bwf.py:44-44 ───
[bug · medium] The PDF is written directly to its final path, and there is no validation that the
response body really is a PDF (an HTTP 200 login/error HTML page >10 KB would also pass). If
`write_bytes` is interrupted (disk full, Ctrl-C) or the server returns an HTML page, the next run
sees `f.exists() and st_size > 10000` and permanently treats the corrupted file as a good cache hit,
so `extract` keeps failing with no way to recover except manual deletion. Write to a temp file,
verify the payload (e.g. `data[:4] == b"%PDF"`), then `f.replace()` atomically.

-         f.write_bytes(data)
+         if not data.startswith(b"%PDF"):
+             raise ValueError(f"not a PDF response ({len(data)} bytes)")
+         tmp = f.with_suffix(".pdf.part")
+         tmp.write_bytes(data)
+         tmp.replace(f)


─── tools/fetch_bwf.py:84-84 ───
[maintainability · low] Both `download` and `extract` swallow every exception and the script still
terminates with exit code 0 even if all six downloads/extractions fail; the summary line then just
prints `合计 0 字`. Any automated/CI invocation of this ingestion step cannot detect the failure. Track
the failed keys and return a non-zero exit status (e.g. `sys.exit(1)` when `files` is empty or any
key failed).



─── tools/probe_questions.py:68-68 ───
[bug · medium] `hits` is indexed without checking for emptiness. `app.retrieve` can return an empty
list (e.g. when `fuse_by_language` yields nothing and rerank returns nothing), and then `hits[0]`
raises `IndexError`, which is swallowed by the broad `except Exception` below and reported as a
generic `ERR` — indistinguishable from a real retrieval failure. Since the whole point of this probe
is to distinguish "no answer in corpus" from "error", handle the empty case explicitly.

+         if not hits:
+             print(f"{code:<5}{cat:<8}{'-':<8}{'':<22}{q[:30]}  (无命中)", flush=True)
+             continue
          top_score, top_c = hits[0]


─── tools/probe_questions.py:77-77 ───
[maintainability · low] The `except` branch only prints the exception type name and discards
`str(e)`, so the actual error message (missing key, API error, etc.) is lost and the row cannot be
diagnosed after the run. Include the message in the output.

-         print(f"{code:<5}{cat:<8}{'ERR':<8}{'':<22}{q[:30]}  {type(e).__name__}", flush=True)
+         print(f"{code:<5}{cat:<8}{'ERR':<8}{'':<22}{q[:30]}  {type(e).__name__}: {e}", flush=True)


─── tools/probe_questions.py:71-74 ───
[maintainability · low] The docstring states the probe must also avoid questions that *are*
answerable in the corpus being used as negative samples (category G), but the flag logic only
highlights low/medium scores. A G question with a high top score (i.e. actually answerable) gets no
flag at all and is easy to miss when scanning the table. Add an explicit high-score flag for
negative samples.

-         if top_score < 0.15:
+         if cat == "负样本" and top_score >= 0.35:
+             flag = "  ⚠️ 负样本但有命中"
+         elif top_score < 0.15:
              flag = "  ⚠️ 低分"
          elif top_score < 0.35:
              flag = "  ? 中等"


─── tools/show_refuse.py:41-41 ───
[bug · medium] 拒答判定使用宽泛的子串匹配（尤其 "没有"、"无法" 这类高频词），会把包含这些词但实为「硬答」的回答误判成「✅ 正确拒答」。例如 
"双打撞拍通常是因为没有沟通跑位" 会被判定为拒答，直接掩盖了本工具想抓出的幻觉，削弱了自动判定的可信度。建议使用更具体的拒答句式（如 "没有收录"、"未收录"、"资料中没有"、"无法回答"
等完整短语），或直接以 agent_core 的无证据分支结果为准，避免误报。



─── tools/show_refuse.py:40-40 ───
[bug · medium] 9 道题串行调用 LLM/agent，任一题抛出异常（网络错误、超时、接口报错等）都会让整个脚本中断，导致前面已跑完的结果和最后的结果文件都无法保存。建议对每题用
try/except 包裹，失败时记录错误继续跑完剩余题目，保证批量评测的鲁棒性。

+     try:
-     steps, answer = agent_core.run(q)
+         steps, answer = agent_core.run(q)
+     except Exception as e:
+         print(f"[{code}] {q}\n  运行失败：{e!r}\n")
+         results.append({"code": code, "question": q, "error": repr(e)})
+         continue


─── tools/probe_80.py:126-127 ───
[bug · medium] `hits[0]` is indexed without checking that `retrieve` returned anything. `retrieve()`
returns `fused[:top_k]`, and `fuse_by_language` can legitimately return an empty list (empty/failed
index, all retrieval paths returning nothing), which makes this raise `IndexError` —
indistinguishable from a real retrieval failure and, worse, the question then never lands in
`suspect`, so the final summary reports it as fine.

              _, hits = app.retrieve(q, 5)
+             if not hits:
+                 raise RuntimeError("检索结果为空")
              s, c = hits[0]


─── tools/probe_80.py:139-139 ───
[maintainability · medium] The caught exception is effectively swallowed: only `type(e).__name__` is
printed, so the actual message (timeout vs. API error vs. empty hits) is lost, and the failed
question is not appended to `suspect` — the closing `需要人工核对的题` count silently excludes every errored
question, which can make a broken run look clean. Print the exception message and record the
failure.

-             print(f"  {code:<6}{'ERR':<7}{'':<6}{'':<6}{'':<18}{q[:26]}  {type(e).__name__}", flush=True)
+             suspect.append((code, q, "可答" if answerable else "拒答", float("nan"), f"ERR:{type(e).__name__}"))
+             print(f"  {code:<6}{'ERR':<7}{'':<6}{'':<6}{'':<18}{q[:26]}  {type(e).__name__}: {e}", flush=True)


─── tools/measure_k.py:74-76 ───
[maintainability · medium] The `safe` loop re-derives each row's `rank` by zipping `gaps` against an
independently filtered copy of `rows`. This only works because the skip condition in the earlier
gaps loop (`len(r["scores"][:6]) >= 2`) happens to be equivalent to this filter (`len(x["scores"])
>= 2`). If either threshold is ever changed, the two lists silently desynchronize and a query's
cliff position gets paired with another query's rank, producing wrong results without any error.
Store the rank directly in the `gaps` tuple (e.g. `gaps.append((top_gap, gap_at, r["q"][:26], s,
r["rank"]))`) and iterate `gaps` directly so the pairing is explicit. Note also that `top_gap` and
`s` unpacked here are never used.

- for g, r in zip(gaps, [x for x in rows if len(x["scores"]) >= 2]):
-     top_gap, gap_at, q, s = g
-     rank = r["rank"]
+ for top_gap, gap_at, q, s, rank in gaps:


─── tools/measure_k.py:81-81 ───
[bug · low] `safe / len(gaps)` divides by `len(gaps)` without guarding against an empty list (the
same applies to the final `sum(g[1] for g in gaps) / len(gaps)`). `gaps` only receives rows whose
hit list has >=2 scores, so if the eval set is smaller/customized or the corpus returns few hits,
`gaps` can be empty and this raises `ZeroDivisionError`. Add a guard before the divisions.

- print(f"\n  断崖法安全率：{safe}/{len(gaps)} = {safe / len(gaps) * 100:.0f}%")
+ print(f"\n  断崖法安全率：{safe}/{len(gaps)} = {(safe / len(gaps) * 100) if gaps else 0:.0f}%")


─── tools/scrape_yonex.py:53-54 ───
[bug · medium] All download failures (DNS/HTTP/timeout/decode) are swallowed here and converted to
`None`, with no logging at all. As a result a systematic failure (e.g. the site blocking the UA, or
a proxy error) looks exactly like "page is 404 / has no title" and the run silently produces a short
output file. Log the exception (id + reason) so failures are diagnosable, and keep returning `None`
only for the "not a product page" case.

-     except Exception:
+     except Exception as e:
+         print(f"抓取失败 {i}: {e}", flush=True)
          return None


─── tools/scrape_yonex.py:43-46 ───
[bug · low] `CACHE.mkdir(...)` and `f.read_text(...)` are outside the `try`, and `parse()` itself
has no error isolation. Any `OSError` raised here (read-only/full disk, network-mounted cache dir,
etc.) propagates out of the worker and through `ex.map`, aborting the whole 1500-page crawl before
`yonex_clean.json` is ever written. Move the cache setup/read inside the guarded block so a single
page can't kill the run.

-     CACHE.mkdir(exist_ok=True)
      f = CACHE / f"{i}.html"
+     try:
+         CACHE.mkdir(parents=True, exist_ok=True)
-     if f.exists():
+         if f.exists():
-         return f.read_text(encoding="utf-8", errors="ignore")
+             return f.read_text(encoding="utf-8", errors="ignore")
+     except OSError as e:
+         print(f"缓存读取失败 {i}: {e}", flush=True)


─── tools/scrape_yonex.py:80-80 ───
[maintainability · low] The id upper bound `1500` is duplicated here and again in the progress
message `f"进度 {done}/1500，有效 ..."`. If the range is ever adjusted the progress output becomes wrong.
Define a single constant (e.g. `MAX_ID = 1500` / `TOTAL = len(ids)`) and reuse it.

      ids = range(1, 1501)
+     total = len(ids)


─── tools/recheck_gaps.py:24-24 ───
[bug · medium] `cs` is always loaded from the hard-coded `chunks_v2.json`, but the retrieval index
inside `app` is built from `RAG_TAG`/`RAG_DATA_DIR` (`CHUNK_CACHE = chunks_{TAG}.json`).
`os.environ.setdefault("RAG_TAG", "v2")` only sets a default — if `RAG_TAG` is already defined in
the environment (or `.env`), `app` will index `chunks_<other>.json` while `cs` still points to
`chunks_v2.json`. `idxs` (indices into `cs`) are then intersected with `top_idx` (indices into
`app.chunks`), comparing positions in two unrelated lists and silently producing wrong verdicts.
Derive the path from the same source the index uses.

- cs = json.loads((ROOT / "chunks_v2.json").read_text(encoding="utf-8"))
+ cs = json.loads((ROOT / f"chunks_{os.getenv('RAG_TAG')}.json").read_text(encoding="utf-8"))


─── tools/recheck_gaps.py:43-43 ───
[documentation · low] Labeling these entries as "语料缺失" conflates two different cases: a question for
which no answer keyword was defined here (so the test cannot run) versus a corpus that genuinely
lacks the content. This can mislead whoever reads the report into believing the corpus is missing
support for these questions. Use wording that reflects "no keyword specified".

-         print(f"{q[:22]:<24}{'—':<14}{'—':<12}语料缺失（无对应关键词）")
+         print(f"{q[:22]:<24}{'—':<14}{'—':<12}未指定关键词（无法判定）")



──────── Project Summary ────────

# Project Review Summary — RAG Evaluation & Tooling

**Scope:** 51 comments across 22 files. Comment density is heavily skewed toward `tools/` (18 of 22 files) with a smaller cluster in `experiments/`. The dominant theme is **evaluation/ingestion tooling that fails silently or misreports results**, which is more dangerous here than in a normal app because these scripts are the source of truth for retrieval quality.

### Top Issues

1. **Unguarded `hits[0]` on empty retrieval results aborts or masks whole evaluations.**
   `app.retrieve` can legitimately return an empty list (`fuse_by_language` / rerank fallback yield nothing). Indexing `hits[0][1]` then raises `IndexError`, which either aborts the run or is swallowed by a broad `except` into a false "gap". Appears in `tools/eval_new.py`, `tools/eval_expanded.py` (two sites), `tools/probe_questions.py`, `tools/probe_80.py`. One shared guard pattern fixes all of them.

2. **`os.environ.setdefault("RAG_TAG"/"RAG_DATA_DIR", ...)` lets stale shell env silently select the wrong corpus.**
   In `tools/check_stability.py`, `tools/compare_term_strategy.py`, and `tools/recheck_gaps.py`, `setdefault` (and `load_dotenv()` non-override) honor an already-exported value, so `index_builder` loads e.g. `chunks_rules.json` while the script reads `chunks_v2.json`. This produces wrong results *with no error* — the worst failure mode for a correctness harness. `check_stability.py` compounds this with a hardcoded `TARGET` chunk index tied to one corpus layout.

3. **Broad `except Exception` swallows the actual error, and scripts still exit 0.**
   `tools/probe_questions.py` and `tools/probe_80.py` print only `type(e).__name__`, discarding `str(e)`, and failed questions are dropped from the "needs manual review" count. `tools/fetch_bwf.py` and `tools/scrape_yonex.py` convert every download/parse failure to `None`/a summary line and terminate successfully even if all downloads fail. `experiments/v2_planner.py` catches `Exception` around JSON parsing, hiding `AttributeError`/`TypeError` from unexpected shapes. Net effect: CI and ingestion steps cannot detect failure.

4. **Refusal detection via broad substring matching inflates scores and hides hallucination.**
   `tools/show_refuse.py` and `tools/eval_expanded.py` treat any answer containing `没有` / `无法` / `没有`-style markers as a "correct refusal", so a hard answer like "双打撞拍通常是因为没有沟通跑位" is misclassified as a valid refusal. This directly corrupts the negative-sample / refusal metrics these tools exist to measure.

5. **Module-level side effects on import.**
   `tools/chunk_quality.py` runs the full PDF-parse/chunk/print pipeline at import (no `if __name__ == "__main__":`), and `tools/compare_sql_vs_rag.py` boots the Streamlit app, loads the vector index, and makes LLM/embedding calls at import. Any future `import` (or test collection) re-triggers expensive, side-effecting work.

6. **`experiments/v2_regression.py` uses a home-grown `is_hit` that diverges from the canonical criterion.**
   It uses exact page equality and case-sensitive keyword matching, whereas `run_eval.is_hit` allows `abs(page diff) <= 1` and compares case-insensitively. The regression harness therefore disagrees with the official eval and will report spurious regressions/passes.

7. **Non-atomic writes and missing output validation in data pipelines.**
   `tools/backup_log.py` writes directly to the final day-granular filename (partial/0-byte backups survive interruption, and `QUERY_LOG_BACKUP_KEEP_DAYS <= 0` deletes the just-created backup). `tools/fetch_bwf.py` writes the PDF to its final path with no "is this actually a PDF?" check, so an HTML error page or truncated file is cached as valid. `tools/extract_glossary.py` overwrites `glossary.json` with an empty chapter list when `data_rules_only/` is absent or globbing yields nothing.

8. **cwd-relative path resolution breaks scripts run outside the repo root.**
   `tools/build_eval_v2.py` and `experiments/v2_regression.py` resolve the corpus path against the current working directory instead of anchoring to the repo root / `__file__` (the pattern other tools use). Running from another directory yields `FileNotFoundError` or, worse, silently loads the wrong file.

9. **Secret leakage in `tools/api_check.py`.**
   It prints a prefix/suffix of `DEEPSEEK_API_KEY` to stdout, which lands in CI logs and pasted issues; for short keys the `[:8]` and `[-4:]` slices overlap and print the *entire* key.

10. **Hardcoded magic numbers that must stay in sync manually.**
    `tools/compare_rerank.py` averages by a literal `3` while looping `range(3)`; `tools/scrape_yonex.py` repeats `1500` in the id bound and progress string. Changes one place, silently wrong elsewhere.

### Module Hotspots

- **`tools/` (eval & probe family):** `eval_expanded.py` (4 comments), `probe_questions.py`, `probe_80.py`, `eval_new.py`, `show_refuse.py` — highest density, all centered on empty-result handling and error/refusal classification.
- **`tools/` (ingestion & ops):** `fetch_bwf.py`, `scrape_yonex.py`, `extract_glossary.py`, `backup_log.py` — atomicity, validation, and silent-failure issues.
- **`tools/` (corpus/env coupling):** `check_stability.py`, `recheck_gaps.py`, `compare_term_strategy.py`, `bm25_check.py`, `measure_k.py`, `compare_rerank.py` — env-override and hardcoded-index fragility.
- **`experiments/`:** `v2_planner.py`, `v2_regression.py`, `v2_retrieve.py` — output-shape validation, eval-criterion drift, and serial-per-requirement cost.

### Cross-Cutting Concerns

- **Silent failure over loud failure.** The repeated instinct is `except Exception: print(type(e).__name__)` and exit 0 (`probe_80.py`, `probe_questions.py`, `fetch_bwf.py`, `scrape_yonex.py`, `bm25_check.py`). Scripts self-described as "smoke tests" have no assertions and no non-zero exit, so they cannot gate CI.
- **No input/state validation before use.** Empty `hits`, missing cache, empty glob, unset env vars (`api_check.py`, `v2_planner.py`) all proceed to a downstream crash or silently wrong output rather than a clear fail-fast.
- **Copy-paste drift in docs and criteria.** Stale run instructions point at files that don't exist (`api_check.py` → `test_api.py`, `chunk_quality.py` → `test_chunker.py`), and `v2_regression.is_hit` reimplements a criterion that already exists canonically.
- **Dead code / unused locals** recur: `api_check.py` `sys.path` bootstrap + `Path` import, `eval_expanded.py` `re` import and `top_c`, `v2_retrieve.py` `score`, `v2_planner.py` unused config validation path.
- **Efficiency nits with real cost:** `v2_retrieve.py` runs a full serial v1 pipeline (LLM rewrite + 9-way retrieval + rerank) per need → N× latency; `build_eval_v2.py` recomputes `kw.lower()` per chunk.

### Quick Wins

- Add a shared `if not hits: continue/return` guard before every `hits[0]` (`eval_new.py`, `eval_expanded.py`, `probe_questions.py`, `probe_80.py`).
- Replace `except Exception` with targeted exceptions and include `str(e)` in output; make `bm25_check.py`/`fetch_bwf.py`/`scrape_yonex.py` exit non-zero on failure.
- Delete dead code: unused `re`/`top_c` in `eval_expanded.py`, `score` unpack in `v2_retrieve.py`, `sys.path` bootstrap and stray `Path` import in `api_check.py`.
- Fix docstring commands to the real filenames (`api_check.py`, `chunk_quality.py`).
- Stop printing any part of the API key in `api_check.py` (print presence/length only).
- Wrap the `setdefault` env setup so an existing `RAG_TAG` cannot silently mismatch the loaded `chunks_*.json` (`check_stability.py`, `compare_term_strategy.py`, `recheck_gaps.py`).
- Derive the average divisor from the loop length in `compare_rerank.py`; define a single `TOTAL`/`MAX_ID` constant in `scrape_yonex.py`.
- Hoist `kw.lower()` out of the comprehension in `build_eval_v2.py`; add `if __name__ == "__main__":` guards to `chunk_quality.py` and `compare_sql_vs_rag.py`.
- Wrap per-question processing in `try/except` in `show_refuse.py` so one failure doesn't discard all completed results.
