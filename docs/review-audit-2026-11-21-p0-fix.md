# 2026-11-21 修复 2026-11-19 审查剩余 3 个 P0

**结论**：3 个 P0 全部修复并落测试，本地提交完成、未推送。全量测试 80 passed（基线 71），
有重排 10 题 10/10，无重排 9/10（基线 8/10，多命中 1 题，已核查非回归）；语料重切为
1113 块 / 581,638 字符 / 16 个来源。P0-4 未在真实服务器执行（本机无部署密钥），
证据为语法检查、`--dry-run` 与本地伪造目录的 5 个场景测试。

来源盘点：`docs/review-audit-2026-11-20.md`；审查原文 `docs/review-*.md`（11 份）。
本批**未改任何 P1**（LIKE 元字符、`decide` 共用 except、评测重复记录、`lstrip` 字符集等）。

---

## P0-1 chunker 引言块粘连

**状态**：已修复（提交 `d01ad7f`）

**根因**（`chunker.py:129` `merge_siblings`）：

- 引言块 `clause` 为空串时，`same_parent = prev_parent == curr_parent or not prev_parent`
  里的 `not prev_parent` 恒真；
- 且 `len("".split(".")) == 1`，后续条款的段数永远不「更短」，
  旧收短条件 `if len(c["clause"].split(".")) < len(prev["clause"].split("."))` 永不成立，
  `prev["clause"]` 一直保持空串，父级比较从此永久失效；
- 结果是引言块一路吞掉后面所有章节的条款直到 `max_len = 1200`，
  块前缀与页码停在第一段，引用定位错误。

**复现**：旧缓存 `chunks_v2.json`（1074 块）中筛出 16 个跨父级混合块，例如
`5. EQUIPMENT` 吞 5.2 + 6.1、`15. SHUTTLE NOT IN PLAY` 吞 16.2 + 16.3、
`12. SERVICE COURT ERRORS` 吞 12.1 + 13.2 + 13.3。另发现 p6 一块 `clause=9.1.5`
但正文从 9.1.4.1 开始（「段数更少」覆盖所致）。

**改法**：

1. 引言块首次吸收条款时写入该条款编号（`prev["clause"] = c["clause"]`），父级比较恢复有效；
2. 新增章节边界（`chunker.py:163`）
   `same_chapter = prev["chapter"] == c["chapter"] or not c["chapter"]`：
   后续块 chapter 为空（跨页后章标题不重复）仍允许合并，明确标了另一章则断开。
   **没有采用审查建议的严格相等**：严格相等会把 Law 14 跨页的 let 条件列表拆开
   （14.2.1 在第 9 页、14.2.7 在第 10 页），已有测试保护；
3. 编号收短改为祖先判断 `prev["clause"].startswith(c["clause"] + ".")`。

**测试**（`tests/test_chunking.py`，+4 例）：

| 用例 | 修前 | 修后 |
|:---|:---|:---|
| `test_merge_siblings_intro_stops_at_parent_boundary` | 红 | 绿 |
| `test_merge_siblings_intro_does_not_cross_new_chapter` | 红 | 绿 |
| `test_merge_siblings_allows_page_break_within_same_parent`（回归保护） | 绿 | 绿 |
| `test_merge_siblings_keeps_first_clause_label_for_deep_siblings` | 红 | 绿 |

`pytest -q tests/test_chunking.py` → 29 passed。

**索引重建与校验**：`RAG_DATA_DIR=data_rules_only python index_builder.py`
（注意：不设该变量时 `document_loader.DATA_DIR` 默认 `data/`，只有 5 个 PDF，
会切出 305 块的错误缓存）：

| 指标 | 改前 | 改后 |
|:---|:---|:---|
| 块数 | 1074 | **1113**（+39） |
| 字符数 | 580,140 | **581,638**（+1,498，新块层级前缀） |
| 来源数 | 16 | 16 |
| `badminton_rules.pdf` 块数 | 40 | 50 |
| 跨父级混合块 | 16 | **0** |
| 编号与正文首条款错位 | 有（至少 1 例 p6） | **0** |
| 最大块 | 7592（`bwf_ranking.txt` 段落回退） | 7592（P2，未动） |

---

## P0-2 向量缓存失效判断

**状态**：已修复（提交 `7e861d9`，配套 `.gitignore` 提交 `a2394de`）

**根因**（`index_builder.py:151` `build_vectors`）：原逻辑只判断
`if len(vecs) == len(chunks)` 就命中。块内容改了但块数不变、或换 embedding 模型但维度相同，
旧向量继续对应新文本，召回静默答错；旧 `.npy` 也没有任何模型/内容标识可供校验。

**改法**：

- `VEC_META = vectors_<tag>.meta.json`，记录
  `fingerprint = sha256(EMBED_MODEL + "\0" + 各块 text + "\0")`、`model`、`count`、`dim`；
- `_chunks_fingerprint`（`index_builder.py:112`）、`_load_cached_vectors`（`index_builder.py:128`）；
- 命中要求：meta 存在且可解析、`model` 与 `EMBED_MODEL` 一致、`fingerprint` 一致、
  `vecs.ndim == 2` 且 `len(vecs) == len(chunks)`；
- 无 meta 的旧缓存、meta 损坏（`JSONDecodeError` ⊂ `ValueError`）、`.npy` 读取失败 → 重建；
- 重建后写 meta；`.gitignore` 增加 `vectors_*.meta.json`（缓存可重建，不提交）。

**测试**（`tests/test_index_cache.py`，新文件，5 例全绿）：

1. 块内容不变 → 命中，且不调用 embedding API；
2. 块数不变、内容改一字 → 必须重建（**旧代码在此路径会错误命中**）;
3. 换 `EMBED_MODEL` → 必须重建；
4. 旧版只有 `.npy` 没有 meta → 必须重建；
5. meta 是非法 JSON → 必须重建。

**实测**：旧 1074 行 `vectors_v2.npy` 无 meta，重建时打印
「缺少指纹文件…按失效处理」，重算 `(1113, 1024)`，写 meta：

```json
{"fingerprint":"7de659e5ee09d8cdf3816eaa05b5fb250f6382d635d01f39d49dd6c22134ed4a",
 "model":"BAAI/bge-m3","count":1113,"dim":1024}
```

---

## P0-4 部署回滚不真正恢复

**状态**：已修复（提交 `e345fa6`）；真实部署未执行

**根因**（`scripts/deploy.sh:168` `backup_script`、`:256` `rollback_script`、`:521` `do_rollback`）：

1. 备份完成后另开一个 ssh，用 `ls -1t backups/*.tar.gz | head -n 1` 再猜一次备份路径。
   并发部署、备份被清理、或本次备份没生成时都会拿错版本——回滚到错误版本比不回滚更危险；
2. `tar -xzf bak -C REMOTE_DIR` 直接覆盖解压：本次部署新增的文件不会消失，
   回滚后是「旧文件 + 新文件」混合状态；
3. 回滚只 `systemctl restart badminton-rag`，`badminton-admin` 继续跑新代码；
   且健康检查的时间戳仍是部署时写的，噪声口径不一致。

**改法**：

- `backup_script` 打印 `BACKUP_PATH=<绝对路径>` 并写 `backups/latest.path`；
  本地捕获该行，捕获不到就中止部署（`set -e` 下备份失败也不会继续）；
- `rollback_script` 逐项校验后再动线上文件：
  备份存在 → `tar -tzf` 归档完整 → 解包到 `REMOTE_DIR/.rollback.XXXXXX` →
  确认 `app.py` 存在 → 整体切换（先删备份里没有的顶层条目，再用备份条目替换，
  保留 `backups/`、`.venv/`）→ 重置重启时间戳 → **同时重启两个服务** → 等待 8 秒；
- `do_rollback` 打印回滚目标路径；回滚后仍跑健康检查，失败明确提示人工介入；
- 失败路径与退出码写进脚本注释：预检/备份失败 `2`（服务器未改动）、
  部署失败但回滚成功 `1`、回滚也失败 `2`（需人工）。

**验证**（证据强度逐项说明）：

| 项 | 结果 | 强度 |
|:---|:---|:---|
| `bash -n scripts/deploy.sh` | 通过 | 语法 |
| `bash scripts/deploy.sh --dry-run` | exit 0，全流程打印，含 `BACKUP_PATH=` 行（`docs/deploy-dry-run-2026-11-21.txt`） | 分支覆盖但不执行 ssh |
| 提取远端脚本本地跑 5 场景 | 全部符合预期，`fail=0` | 真执行生成的远端脚本，`systemctl` 用 stub，目录用临时目录 |
| 真实服务器部署 + 回滚 | **未执行**（本机无 `/tmp/brag.pem`） | 无 |

5 个场景：

1. 正常回滚：`app.py`/`tools/q.py` 恢复旧内容，`old_only.py` 回来，
   部署新增的 `new_file.py`、`tools/new.py` 被删除，`backups/`、`.venv/` 保留；
2. 归档损坏：exit 4，`app.py` 仍是新版本（线上未被改动）；
3. 归档缺 `app.py`：exit 5，线上未被改动；
4. 备份不存在：exit 1；
5. `BACKUP_PATH=` 可捕获、路径真实存在、`backups/latest.path` 内容一致、归档含 `app.py`。

> 场景 1 首轮实现曾把「删除多余条目」放在「替换」之后，导致刚还原的文件又被删掉；
> 本地场景测试发现后已把顺序改为「先删多余、再替换」，最终 5 场景通过。
> 这正是没有真实服务器时仍要跑生成脚本的原因。

---

## 验证数字汇总

| 项 | 基线（2026-11-20） | 本次 |
|:---|:---|:---|
| `pytest -q` | 71 passed, 4 skipped, 4 deselected | **80 passed, 4 skipped, 4 deselected** |
| 10 题 `RAG_RERANK=true` | 10/10 | **10/10** |
| 10 题 `RAG_RERANK=false` | 8/10（未命中：60 秒间歇、正手高远球常见错误） | **9/10**（未命中：正手高远球常见错误） |
| 块数 / 字符 / 来源 | 1074 / 580,140 / 16 | **1113 / 581,638 / 16** |
| 向量形状 | (1074, 1024) 无 meta | **(1113, 1024) + meta** |

无重排 9/10 的差异已核查：多命中的「60 秒的间歇出现在什么时候」，
是 `bwf_laws_2027.txt` 的块在切块修复后边界变化、关键词进入 top5，
答对且引用成立，属改善；剩余未命中与基线失败模式一致
（页码命中 `tech_high_clear.txt 第1页`，块内无「击球点选择不当」），非本次引入。
有重排口径不变。因块数变化，无重排口径不与旧 top5 逐题对比，只对照命中清单。

---

## 提交清单（本地，未推送）

| 提交 | 内容 |
|:---|:---|
| `d01ad7f` | fix: 切块引言块不再跨父级吞并条款（P0-1） |
| `7e861d9` | fix: 向量缓存按内容指纹与模型标识失效（P0-2） |
| `e345fa6` | fix: 部署回滚改为真正还原上一版本（P0-4） |
| `a2394de` | chore: 忽略向量缓存指纹文件（P0-2 配套） |
| 本次文档提交 | README/技术手册/面试话术块数同步、变更记录、评测与 dry-run 证据、本报告 |

基线 HEAD 为 `2fbab4e`；以上 4 个代码提交之后，文档提交为其后一条。

## 工作区状态

文档提交后工作区只剩一个与本批无关的历史未跟踪文件
`docs/eval-hybrid-zero-80.err`（2026-11-19 80 题诊断的 stderr，未提交）。
`chunks_v2.json`、`vectors_v2.npy`、`vectors_v2.meta.json` 为本地重建缓存，已被 `.gitignore` 忽略。

## 剩余风险 / 没做的事

1. **真实部署与线上回滚未实跑**：无 SSH 密钥。P0-4 的结论只覆盖脚本逻辑与本地场景，
   真实服务器的 `systemctl`、路径权限、磁盘空间未验证。第一次真实部署建议先看
   `backups/latest.path` 是否与输出一致，再手动验证一次回滚。
2. **`deploy.sh --with-index` 未包含 `vectors_v2.meta.json`**：只传 `.npy` 时线上会判定失效
   并调用 embedding API 重建（安全，但多一次费用与启动延迟）。要么把 meta 加进
   `INDEX_FILES`，要么接受重建。本轮未改（避免扩大 P0-4 范围）。
3. **`chunks_v2.json` 仍只按语料 mtime 失效**：只改 `chunker.py` 不删缓存会继续用旧块。
   本次是手动删除后重建；线上更新切块逻辑必须同时传索引或删缓存。
4. **P1 全部未动**，按用户决定。顺带发现但未改：`chunker.py` 的 `_parent` 对无编号块
   返回空串，依赖 `not prev_parent` 的宽松合并仍可能让「无编号引言」跨页吸收同章条款
   （当前语料未触发，已有跨章测试兜底）。
5. 最大块 7592 字符（`bwf_ranking.txt` 段落回退）未处理（P2）。
6. 80 题评测集（`tools/eval_80.py`）未重跑：本轮 gate 只要求 10 题两口径，
   而 80 题依赖 LLM 生成、耗时长；块数变化后 97.1% 的历史数字未重新验证。