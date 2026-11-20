# 2026-11-21 修复 2026-11-19 审查剩余 3 个 P0

**编号**：2026-11-21-p0-review-fixes
**状态**：已采纳
**来源**：`docs/review-audit-2026-11-20.md` P0-1 / P0-2 / P0-4（P0-3 已于 2026-11-19 修复）

### 范围

| 文件 | 角色 |
|:---|:---|
| `chunker.py` | P0-1 被测代码（`merge_siblings`） |
| `tests/test_chunking.py` | P0-1 规格测试（+4 例） |
| `index_builder.py` | P0-2 被测代码（`build_vectors` 缓存判断） |
| `tests/test_index_cache.py` | P0-2 规格测试（+5 例，新文件） |
| `scripts/deploy.sh` | P0-4 备份路径捕获与回滚 |
| `README.md`、`docs/项目技术手册.md`、`docs/面试话术.md` | 块数/块均字数同步（1074 → 1113） |

### 改动

#### P0-1 引言块跨父级粘连（`chunker.py:merge_siblings`）

引言块的 `clause` 是空串时，`same_parent = prev_parent == curr_parent or not prev_parent` 恒真；
且 `len("".split(".")) == 1`，后续条款的段数永远不「更短」，编号一直保持空串，
父级比较从此失效。于是一个引言块会一路吞掉后面所有章节的条款，直到 `max_len`，
块头的前缀和页码却停在第一段——引用定位错误。旧缓存 1074 块里有 16 个这样的混合块
（例：`15. SHUTTLE NOT IN PLAY` 吞掉 16.2、16.3；`5. EQUIPMENT` 吞掉 5.2、6.1）。

修法三条：

1. 引言块首次吸收条款时写入该条款编号（`prev["clause"] = c["clause"]`），父级比较恢复有效；
2. 增加章节边界 `same_chapter = prev["chapter"] == c["chapter"] or not c["chapter"]`：
   后续块 chapter 为空（跨页后章标题不重复）仍允许合并，明确标了另一章则断开。
   没有采用审查建议的严格相等——严格相等会拆散 Law 14 跨页的 let 条件列表
   （14.2.1 在第 9 页、14.2.7 在第 10 页），已有 `test_merge_siblings_allows_page_break_within_same_parent` 保护；
3. 编号收短改为祖先判断 `prev["clause"].startswith(c["clause"] + ".")`，不再用段数。
   旧规则把从 9.1.4.1 开始的块错标成 9.1.5（`9.1.4.1 + 9.1.5` 时 9.1.5 段数更少）。

#### P0-2 向量缓存失效判断（`index_builder.py:build_vectors`）

原逻辑只判断 `len(vecs) == len(chunks)`。块内容改了但块数不变、或换 embedding 模型但维度相同时，
旧向量继续对应新文本，召回静默答错。

改为 `vectors_<tag>.meta.json` 记录 `sha256(模型名 + 各块文本)` 指纹、模型名、块数、维度；
命中要求指纹与模型一致、块数与形状匹配。无 meta 的旧缓存、meta 损坏、读取失败一律重建。

#### P0-4 部署回滚不真正恢复（`scripts/deploy.sh`）

三处问题：

1. 备份路径在备份完成后另开一个 ssh 用 `ls -1t backups/*.tar.gz | head -n 1` 再猜一次，
   并发部署、备份被清理、或本次备份没生成时会拿错版本；
2. `tar -xzf bak -C REMOTE_DIR` 直接覆盖解压，本次部署新增的文件不会消失，回滚后仍是混合状态；
3. 回滚只重启 `SERVICE_NAME`，管理后台仍跑新代码。

修法：

- `backup_script` 自己打印 `BACKUP_PATH=<绝对路径>` 并写 `backups/latest.path`，
  本地从输出捕获；捕获不到路径就中止部署，不在无备份保障下改服务器；
- 回滚先 `tar -tzf` 校验归档、解包到 `REMOTE_DIR/.rollback.XXXXXX` 并确认 `app.py` 存在，
  确认后才整体切换：先删备份里没有的顶层条目，再用备份条目整份替换（保留 `backups/`、`.venv/`）；
- 切换后同时重启 `SERVICE_NAME` / `ADMIN_SERVICE_NAME`，重置 `/tmp/badminton-rag-restart.ts`，
  再跑健康检查；
- 失败路径与退出码写进脚本注释（预检 2 / 部署失败但回滚成功 1 / 回滚失败需人工 2）。

### 锚点

| 文件 | blob hash |
|:---|:---|
| `chunker.py` | `b810329d44150744b5d43ba4b4208d9c1272b8db` |
| `tests/test_chunking.py` | `b9087d6499827ef9cd68777eae717e542a854b74` |
| `index_builder.py` | `dfe551737d5f6e31304ed009a2053e465eae5125` |
| `tests/test_index_cache.py` | `4ecfd3210f33611c0bdff6063408a4a5d9ab9418` |
| `scripts/deploy.sh` | `443cd5c2b89d8843c73cab36f7dfce59a9f71bd0` |

```bash
git hash-object chunker.py tests/test_chunking.py index_builder.py \
  tests/test_index_cache.py scripts/deploy.sh
```

### 验收 gate

| 项 | 内容 |
|:---|:---|
| 命令 | `pytest -q` |
| 判据 1 | 全部通过；基线 71 passed，新增 9 例后 80 passed / 4 skipped / 4 deselected |
| 命令 | `RAG_DATA_DIR=data_rules_only python run_eval.py`（`RAG_RERANK=true`） |
| 判据 2 | Recall@5 = 10/10，不低于基线 |
| 命令 | `RAG_DATA_DIR=data_rules_only RAG_RERANK=false python run_eval.py` |
| 判据 3 | 与无重排基线 8/10 对比，逐题确认无新增退化（实测 9/10，见裁决） |
| 命令 | `bash -n scripts/deploy.sh`；`bash scripts/deploy.sh --dry-run` |
| 判据 4 | 语法通过、dry-run exit 0，且输出中备份/回滚脚本含 `BACKUP_PATH=` |
| 命令 | 提取 `backup_script` / `rollback_script` 生成的远端脚本，在本地伪造目录跑 5 个场景 |
| 判据 5 | 正常回滚还原内容并删除残留、归档损坏/缺 app.py/备份不存在三种失败均不改线上文件、`BACKUP_PATH` 可捕获 |
| 不适用 | 真实服务器部署：本机无 `/tmp/brag.pem`，未执行；证据强度见报告「P0-4」小节 |

### 证据

| 文件 | 内容 |
|:---|:---|
| `docs/eval-p0fix-rerank.txt` | 10 题，`RAG_RERANK=true`，Recall@5 = 10/10 |
| `docs/eval-p0fix-norerank.txt` | 10 题，`RAG_RERANK=false`，Recall@5 = 9/10，未命中「正手高远球最容易犯的错误」 |
| `docs/deploy-dry-run-2026-11-21.txt` | `deploy.sh --dry-run` 全流程输出（exit 0） |

测试：`pytest -q` → `80 passed, 4 skipped, 4 deselected`。

### 结果

三条 P0 均修复，带回归测试。重切语料后 **1113 块 / 581,638 字符 / 16 个来源**（原 1074 / 580,140 / 16）；
新增 39 块，多出的字符是新块的层级前缀。校验：0 个跨父级混合块、0 个编号与正文首条款错位；
`badminton_rules.pdf` 40 → 50 块。

### 裁决

无重排口径由 8/10 变为 9/10，多命中「60 秒的间歇出现在什么时候」。
原因是该题命中的 `bwf_laws_2027.txt` 块在切块修复后边界变化，关键词进入了 top5，属改善而非回归；
另一道未命中「正手高远球最容易犯的错误」与基线失败模式完全一致
（页码到了 `tech_high_clear.txt 第1页`，但块内没有「击球点选择不当」），不是本次改动引入。
有重排 10/10 与基线一致。因块数变化，无重排口径与旧基线的逐题 top5 不可逐字节对比，
但 10 题全量结果与未命中清单已记录在证据文件中。

### 遗留

- P1 全部未动（LIKE 元字符、`decide` 共用 except、评测重复记录、`lstrip` 字符集等），按用户决定本批不处理。
- `chunks_<tag>.json` 缓存仍只按语料 mtime 失效：只改 `chunker.py` 而不删缓存会继续用旧块。
  本次本地重建时手动删除；线上更新切块逻辑需同时 `--with-index` 或删缓存。
- `vectors_<tag>.meta.json` 是新文件，`deploy.sh --with-index` 的 `INDEX_FILES` 未包含它；
  若只传 `vectors_v2.npy` 而不传 meta，线上会判定失效并调用 API 重建（安全，但会多一次费用）。
- 最大块 7592 字符仍是 `bwf_ranking.txt` 的段落回退块（P2，本轮不动）。
- 真实部署与线上回滚未实跑（无密钥），P0-4 的结论来自语法检查、dry-run 与本地伪造目录场景测试。

### 回滚

```bash
git revert e345fa6   # P0-4 部署回滚
git revert 7e861d9   # P0-2 向量缓存
git revert d01ad7f   # P0-1 切块
rm -f chunks_v2.json vectors_v2.npy vectors_v2.meta.json
RAG_DATA_DIR=data_rules_only python index_builder.py
```

回滚后重跑 `pytest -q` 与两种口径的 10 题评测，确认回到 1074 块 / 10/10 / 8/10。