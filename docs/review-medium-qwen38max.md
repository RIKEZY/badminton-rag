
─── examples/minimal_demo.py:31-32 ───
[bug · high] PDF 路径与仓库实际数据目录不一致：本项目的语料目录是
`data_rules_only/`（`app.py`、`agent_tools.py`、`tests/conftest.py` 等均设置
`RAG_DATA_DIR=data_rules_only`，PDF 实际位于 `data_rules_only/badminton_rules.pdf`），仓库中并不存在 `data/`
目录。因此按文档运行 `python examples/minimal_demo.py` 会在 `check_config()` 里直接 `sys.exit("找不到
PDF：...")`，这个冒烟示例根本无法跑通；下面的报错提示「把羽毛球规则 PDF 放进 data/ 目录」也会把用户引向错误位置。建议与其余脚本保持一致，读取
`RAG_DATA_DIR`（默认回落到 `data_rules_only`）。

  ROOT = Path(__file__).resolve().parent.parent
- PDF_PATH = ROOT / "data" / "badminton_rules.pdf"
+ DATA_DIR = Path(os.getenv("RAG_DATA_DIR") or (ROOT / "data_rules_only"))
+ PDF_PATH = DATA_DIR / "badminton_rules.pdf"


─── tools/equipment_query.py:50-52 ───
[bug · medium] `weight` is used as a raw dict key against `tension_json`, whose keys are produced by
`parse_tension()` and are always uppercase (`'4U'`, `'3U'`, `'5U'`). Unlike `model`, the argument is
not normalized, so `tension_of("88S PRO", "4u")` or `"4 u"` silently returns `{"range": None}` —
indistinguishable from the legitimate "this racket has no such spec" case already covered by the
tests. The caller (and ultimately the user question) gets a wrong "unknown tension" answer instead
of the real value. Normalize the weight the same way the model is normalized.

  def tension_of(model: str, weight: str | None = None):
      """查磅数；指定 weight（如 '4U'）时只返回该规格"""
+     weight = normalize(weight) or None
      rows = search_model(model)


─── tools/equipment_query.py:40-40 ───
[bug · low] `normalize()` strips spaces, `-` and `_`, but not `%`, which is a LIKE wildcard. A
keyword containing `%` therefore reproduces exactly the "matches every row" failure the docstring
above warns about, and the caller silently gets an arbitrary racket back. Escape LIKE metacharacters
(with `ESCAPE`) before building the pattern.

-     like = f"%{kw}%"
+     esc = kw.replace("\\", "\\\\").replace("%", "\\%")
+     like = f"%{esc}%"  # 配合 SQL 末尾的 ESCAPE '\'


─── tools/equipment_query.py:14-15 ───
[bug · low] `sqlite3.connect()` on a missing path creates an empty 0-byte file instead of failing.
If `equipment.db` was never built or a deploy left it out, every query here raises a confusing
`sqlite3.OperationalError: no such table: rackets` *and* leaves a bogus empty DB behind — which then
defeats existence checks such as `tests/conftest.py`'s `EQUIPMENT_DB.exists()` skip, turning a clean
skip into an error. Fail fast with a clear message instead.

+     if not DB.exists():
+         raise FileNotFoundError(f"缺少装备库 {DB}，先跑 tools/build_equipment_db.py")
      conn = sqlite3.connect(DB)
      conn.row_factory = sqlite3.Row


─── agent_tools.py:33-33 ───
[bug · medium] `search_model()` 是模糊 LIKE 查询并按 `LENGTH(model)`
排序，一次可能命中多款球拍（例如输入「天斧」「88」「100ZZ」这类不完整型号）。这里直接取 `rows[0]` 并把结果标记为
`found=True`，等于把“任意一款最短型号名的匹配”当成用户想要的型号，再经 `describe_racket`/`format_racket_evidence`
以权威口吻呈现给模型和用户——这与本文件“精确值不过 LLM、不编造”的设计原则相冲突，且调用方无法察觉存在歧义。
建议：命中多行时把候选一并返回（或在结果里带上 `match_count` / `candidates`），由上层决定是追问用户还是明确说明取的是哪一款。



─── agent_tools.py:99-99 ───
[maintainability · low] 用户可见文案里硬编码了「库里现有 34 款」，而库的真实条数由 `equipment.db`
决定（`tools/build_equipment_db.py` 会重建/扩充数据）。一旦数据变化，这句话就会变成错误信息，而且是在“未命中”这种最需要可信度的场景下输出。建议改为动态获取条数（如
`SELECT COUNT(*) FROM rackets`，可加模块级缓存），或直接去掉数字。



─── agent_tools.py:102-105 ───
[maintainability · low] 这份 7 项 `(label, key)` 映射在本文件的 `format_racket_evidence()`
中被完整重复了一遍（`agent_core.py` 里还有第三份）。三处必须手工保持同步，新增字段时极易漏改导致渲染不一致。建议提取为模块级常量（如
`RACKET_FIELDS`）并在两个函数中共用。



─── .github/workflows/ci.yml:5-9 ───
[performance · medium] No `concurrency` group is defined. Since the workflow triggers on both `push`
to `main` and every `pull_request` event, a branch that has an open PR will start two duplicate runs
per push, and rapid successive pushes queue up multiple full runs (dependency install + corpus build
+ pytest), wasting runner minutes. Add a top-level concurrency block, e.g.:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```



─── .github/workflows/ci.yml:11-12 ───
[security · medium] The workflow does not declare a `permissions` key, so the `GITHUB_TOKEN`
inherits the repository/org default (often write scope on several permission groups) even though
this job only needs to read the checkout. Under least privilege, pin it down explicitly:

```yaml
permissions:
  contents: read
```

+ permissions:
+   contents: read
+ 
  jobs:
    test:


─── .github/workflows/ci.yml:13-13 ───
[other · medium] The job has no `timeout-minutes`. If dependency installation, `build_chunks()`, or
the pytest run hangs (e.g. a network stall while resolving pip packages, or a test that waits on a
socket), the job keeps consuming a GitHub-hosted runner until the 6-hour platform default. Add an
explicit bound, e.g. `timeout-minutes: 15`.

      runs-on: ubuntu-latest
+     timeout-minutes: 15


─── .github/workflows/ci.yml:55-55 ───
[security · medium] Two problems with this guard step:

1. `|| true` swallows *any* failure of the whole pipeline, not just `grep`'s "no match" exit code 1.
If `git ls-files` fails (bad repo state, checkout problem), `bad` is empty and the step happily
prints "未发现敏感文件" and passes — the security check silently becomes a no-op. Prefer testing grep's
exit status explicitly, e.g. run `git ls-files > tracked.txt` first (so a real failure fails the
step), then `bad=$(grep -E '...' tracked.txt || true)`.

2. The pattern `(^|/)\.env$` only matches a file named exactly `.env`. The very common variants
`.env.local`, `.env.production`, `.env.ci` (all frequently created by dotenv workflows) slip
through, as do key files like `*.pem` / `id_rsa`. Consider `(^|/)\.env(\..+)?$`.

Also note this check only inspects the current tree — as the comment itself says, anything already
in git history stays there, so this cannot remediate a past leak.




──────── Project Summary ────────

### Top Issues

1. **Wrong or arbitrary racket results from fuzzy query handling**  
   `tools/equipment_query.py` does not escape LIKE wildcards in `normalize()`, so a query containing `%` can match every row. `agent_tools.py` compounds this by taking `rows[0]` from a fuzzy `LIKE` query and marking it as `found=True`, which can silently select an arbitrary shortest match. Together these create user-visible incorrect equipment answers.

2. **Missing `equipment.db` is handled unsafely**  
   `tools/equipment_query.py` calls `sqlite3.connect()` directly. If `equipment.db` does not exist, SQLite creates an empty 0-byte database instead of failing cleanly, then queries fail with `no such table: rackets`. This makes deployment or setup failures confusing and can leave a bogus DB file behind.

3. **Demo uses a corpus path inconsistent with the rest of the repo**  
   `examples/minimal_demo.py` references a PDF location that does not match the actual runtime convention. `app.py`, `agent_tools.py`, and `tests/conftest.py` use `RAG_DATA_DIR=data_rules_only`, with the PDF at `data_rules_only/badminton_rules.pdf`. The demo is therefore likely to fail immediately.

4. **Tension lookup is case-sensitive and not normalized**  
   In `tools/equipment_query.py`, `weight` is used directly as a key into `tension_json`, whose keys are uppercase such as `'4U'`, `'3U'`, and `'5U'`. Inputs like `"4u"` or `"4 u"` silently return `{"range": None}` instead of being normalized.

5. **Hardcoded inventory count can become false user-facing text**  
   `agent_tools.py` hardcodes “34 款” in user-visible copy, while the actual count comes from `equipment.db`. If the database is rebuilt or expanded, this message becomes incorrect, especially problematic in a no-match fallback.

6. **CI sensitive-file guard can silently pass even when broken**  
   `.github/workflows/ci.yml` uses a guard where `|| true` swallows any pipeline failure, not just `grep` finding no match. If `git ls-files` fails, the step can still print success and pass, defeating the intended safeguard.

7. **CI workflow lacks basic resource and permission hardening**  
   `.github/workflows/ci.yml` has no `concurrency` group, no explicit `permissions`, and no `timeout-minutes`. This can cause duplicate queued runs, excessive token privileges, and hung jobs consuming GitHub-hosted runners.

8. **Racket field metadata is duplicated across modules**  
   `agent_tools.py` repeats a `(label, key)` mapping that is also duplicated in `agent_core.py`. This creates a maintenance risk where adding or renaming a field can lead to inconsistent rendering.

### Module Hotspots

- **`.github/workflows/ci.yml`**  
  Highest comment count: missing concurrency controls, missing explicit permissions, missing timeout, and a fragile sensitive-file guard.

- **`tools/equipment_query.py`**  
  High severity concentration around query correctness and runtime robustness: LIKE wildcard escaping, weight-key normalization, and unsafe missing-database handling.

- **`agent_tools.py`**  
  Multiple user-facing correctness issues: arbitrary fuzzy-match selection, hardcoded inventory count, and duplicated racket field mapping.

- **`examples/minimal_demo.py`**  
  Lower comment count but high onboarding impact because the demo path does not match the repository’s actual data layout.

### Cross-Cutting Concerns

- **Silent wrong results instead of explicit failures**  
  Represented by `tools/equipment_query.py` returning arbitrary matches or empty tension ranges, and `agent_tools.py` selecting `rows[0]` from multiple fuzzy matches.

- **Configuration and path drift between entrypoints**  
  `examples/minimal_demo.py` diverges from the data-directory convention used by `app.py`, `agent_tools.py`, and `tests/conftest.py`.

- **Duplicated domain metadata and hardcoded facts**  
  `agent_tools.py` and `agent_core.py` duplicate field mappings; `agent_tools.py` also hardcodes a database-derived count.

- **CI robustness and least-privilege gaps**  
  `.github/workflows/ci.yml` lacks concurrency cancellation, explicit read-only permissions, timeout limits, and a reliable guard-step failure mode.

- **Missing fail-fast handling for absent build artifacts**  
  `tools/equipment_query.py` creates an empty SQLite DB when `equipment.db` is missing instead of failing immediately with a clear setup error.

### Quick Wins

- Point `examples/minimal_demo.py` to `data_rules_only/badminton_rules.pdf`, or make it read the same `RAG_DATA_DIR` convention used elsewhere.

- In `tools/equipment_query.py`, normalize `weight` before lookup, for example by uppercasing and stripping spaces/hyphens/underscores.

- In `tools/equipment_query.py`, escape LIKE metacharacters such as `%`, `_`, and `\` before building the SQL pattern.

- In `tools/equipment_query.py`, check that `equipment.db` exists before connecting, or open it in read-only SQLite URI mode so a missing file fails immediately.

- In `agent_tools.py`, remove the hardcoded “34 款” text or replace it with a live `COUNT(*)` query.

- In `agent_tools.py`, avoid treating the first fuzzy match as definitive when multiple models match; return candidates or require a stricter match.

- Extract the repeated racket field mapping into a shared constant used by `agent_tools.py` and `agent_core.py`.

- In `.github/workflows/ci.yml`, add:
  - `concurrency` with `cancel-in-progress: true`
  - `permissions: contents: read`
  - `timeout-minutes`
  - a sensitive-file guard that distinguishes `grep` no-match from real command failures.
