# 2026-11-19 run_eval.py 增加 RAG_RERANK 开关

**编号**：2026-11-19-eval-rerank-toggle
**状态**：已采纳

### 范围

| 文件 | 角色 |
|:---|:---|
| `run_eval.py` | 评测工具（不是被检索链路调用的代码） |

### 改动

`run_eval.py` 增加 `RAG_RERANK`（默认关）与 `RERANK_POOL`（默认 20，下限 `TOP_K`）。开启后融合出候选池，走 `rerank.rerank` 再截断到 `TOP_K`，实现与 `app.retrieve` 对齐：问题 + 首条改写取 `max`，`top_n=len(docs)`，异常回退 `fused[:TOP_K]`。启动时打印当前重排状态。

### 锚点

| 文件 | blob hash |
|:---|:---|
| `run_eval.py` | `dace83e4a3d05bca1713a3c909e7db28faab9956` |

```bash
git hash-object run_eval.py
```

### 验收 gate

| 项 | 内容 |
|:---|:---|
| 命令 | `RAG_RERANK=true python run_eval.py`（10 题） |
| 判据 | 结果与 `docs/项目技术手册.md` 对照实验表「有重排 10/10」一致 |
| 命令 | `python run_eval.py`（不设开关，10 题） |
| 判据 | 默认关闭时结果与改动前一致（8/10） |
| 不适用 | 开关只改测量口径，不改检索链路本身；此记录不证明检索质量变化。 |

### 证据

| 文件 | 内容 |
|:---|:---|
| `docs/eval-hybrid-rerank10.txt` | `RAG_RERANK=true @ 2026-11-19 23:03:48`，10 题，Recall@5 = 10/10 |
| `docs/eval-hybrid-recall10.txt` | 无重排，10 题，Recall@5 = 8/10 |

### 结果

有重排 10/10，无重排 8/10。文档对照实验表为有重排 10/10、无重排 9/10。

### 裁决

有重排口径与文档一致。无重排 8/10 与文档 9/10 差 1 题，在 10 题样本上属噪声量级，不构成回归证据；且本轮检索代码已由 A/B 逐题 top5 一致性独立验证。属测量口径不一致，非回归。

此记录的意义不是"通过了"，而是把 8/10 这个数字的来源固定下来：以后任何引用 `docs/eval-hybrid-recall10.txt` 的地方，都必须同时说明它是无重排配置。

### 遗留

`tools/eval_80.py` 仍带 `top1 rerank 分数 >= 0.3` 的代理指标，此指标已被判定不可靠。后续 gate 不再使用它；该脚本尚未清理，留在 index_builder 那批一起处理。

### 回滚

还原 `run_eval.py` 中 `RERANK_ENABLED` / `RERANK_POOL` 及 `pool`、`rerank` 相关分支，恢复到固定 `pool = TOP_K` 的版本。回滚后 `docs/eval-hybrid-rerank10.txt` 与 `docs/eval-hybrid-recall10.txt` 不再可复现，需在文件头标注失效。
