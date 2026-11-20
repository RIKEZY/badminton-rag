# 2026-11-19 BM25 检索过滤零分块

**编号**：2026-11-19-hybrid-bm25-zero-filter
**状态**：已采纳

### 范围

| 文件 | 角色 |
|:---|:---|
| `hybrid.py` | 被测代码（`bm25_search_idx`） |
| `tests/test_retrieval_hybrid.py` | 规格测试（+3 例） |

### 改动

`bm25_search_idx` 在截断前先过滤 `score > 0` 的块，并保留原下标；`k <= 0` 直接返回 `[]`。

原实现 `sorted(range(len(scores)))[:k]` 在正分块不足 `k` 时，会用零分块按下标顺序补位，把语料最前面的块当成命中送进 RRF。

触发条件不是"完全没命中"，是"正分块数 < 候选池"。实测 `interval`：16 个正分块、候选池 20，混入 4 个零分块；`zzzzqqqq`：0 个正分块、候选池 20 全部是零分块。

### 锚点

| 文件 | blob hash |
|:---|:---|
| `hybrid.py` | `1b79f15a63339efa5c1d797b6fb3106d471eae51` |
| `tests/test_retrieval_hybrid.py` | `faeeed391b79e92f2de4c4a8f081d83568eb757e` |

```bash
git hash-object hybrid.py
git hash-object tests/test_retrieval_hybrid.py
```

> 当前 worktree 还有 `agent_core.py`、`agent_tools.py`、`tools/equipment_query.py`、`.gitignore` 的未提交改动，与本条无关，因此不做全仓 diff 锚点。

### 验收 gate

| 项 | 内容 |
|:---|:---|
| 命令 | `pytest -q tests/test_retrieval_hybrid.py` |
| 判据 1 | 全部通过，且新增 3 例覆盖：正分块少于候选池、全零分、`k=0` |
| 判据 2 | 测试断言**下标集合**，不只断言条数 |
| 命令 | `python run_eval.py`（10 题，`RAG_RERANK=true`） |
| 判据 3 | Recall@5 不低于改前基线，且逐题 top5 集合无新增退化 |
| 命令 | `python tools/eval_80.py`（80 题） |
| 判据 4 | 零结果题数不增加；逐题对照零结果题号清单 |
| 不适用 | 本 gate 只衡量"检索是否塌陷"，不衡量答案正确性。80 题的 `78/80` 是非零结果率，不是准确率。 |

### 证据

| 文件 | 内容 |
|:---|:---|
| `docs/eval-hybrid-rerank10.txt` | 10 题，`RAG_RERANK=true`，Recall@5 = 10/10 |
| `docs/eval-hybrid-recall10.txt` | 10 题，无重排，Recall@5 = 8/10 |
| `docs/eval-hybrid-ab-10.txt` | 10 题 A/B，旧/新 top5 逐题一致，均 8/10（无重排） |
| `docs/eval-hybrid-zero-80.txt` | 80 题 A/B：`measured=80 errors=0 old_zero=0 new_zero=0 regressed=0` |
| `docs/eval-hybrid-diagnose.txt` | BM25 分数分布与触发条件复现 |

测试：`pytest -q tests/test_retrieval_hybrid.py` → `15 passed`。

### 结果

通过。本条改动在实测中影响为零，属防御性修复，不是检索质量提升。

### 裁决

10 题 Recall@5 为 8/10，与文档 10/10 不一致。经查文档 10/10 出自「有重排」配置，`run_eval.py` 无 rerank，对应无重排基线为 9/10。属测量口径不一致，非回归。

补测有重排 10 题为 10/10，与文档一致，口径已对齐。8/10 与 9/10 相差 1 题，在 10 题样本上属噪声量级，不单独作为退化证据；退化判定以逐题 top5 集合 diff 为准。

### 遗留

无（`run_eval.py` 的 `RAG_RERANK` 开关已补，见 `2026-11-19-eval-rerank-toggle.md`）。

### 回滚

```python
order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
return [(float(scores[i]), i) for i in order[:k]]
```

同时删除 `tests/test_retrieval_hybrid.py` 中新增的 `_tiny_bm25` 及 3 个用例。回滚后重跑 `pytest -q` 与 80 题零结果对照。
