# 2026-11-21 跨页续行回粘

**编号**：2026-11-21-cross-page-continuation
**状态**：已采纳
**来源**：用户提出的切块质量修复（页首无编号半句块单独成块）

### 范围

| 文件 | 角色 |
|:---|:---|
| `chunker.py` | 被测代码（`merge_siblings` 新增前置规则） |
| `tests/test_chunking.py` | 规格测试（+10 例：1 回粘 + 6 句末标点 + 1 跨章 + 1 DEFINITIONS + 1 超长） |
| `README.md` | 当前块数同步（1113 → 1112），版本表加 v11 |
| `docs/项目技术手册.md`、`docs/面试话术.md` | 当前块数同步（1113 → 1112） |

### 改动

PDF 翻页会把一句话切成两半：页尾半句是条款 2.3.3 的最后一句
（所在块此前已吸收 2.3.2 / 2.3.3，`clause` 标签仍是 2.3.1），页首半句没有条号，
按条号切时被单独切成 `clause=""` 的一块，开头就是半句话。此前
`badminton_rules.pdf` 第 3 页的 `properties of synthetic materials...` 就是这样
（旧缓存第 15 块，`prefix=[Law 2. SHUTTLE]`，451 字符）。

在 `merge_siblings` 的合并循环里新增一条**前置规则**，在常规合并之前判断：

```python
if (c["clause"] == ""
        and prev["clause"] not in ("", "DEFINITIONS")
        and prev["chapter"] == c["chapter"]
        and not prev["text"].rstrip().endswith(SENTENCE_END)):
    prev["text"] = prev["text"] + "\n" + c["text"]
    continue
```

`SENTENCE_END = (".", "!", "?", ";", ":", ")")`。命中后：

- `prev` 的 `clause` / `chapter` / `page` 不变，页码仍是句子起点的页；
- 被粘的块不再单独成块；
- 允许 `prev["text"]` 超过 `max_len=1200`（内容完整性优先）。

三个关键取舍：

1. **不能用「clause 为空」单独判定**。章节引言块也是 `clause=""`，
   例如 `Law 3. TESTING A SHUTTLE FOR SPEED` 后面的总述；它的 `prev` 是
   上一章最后一块，`chapter` 不同，靠章相等挡掉。
2. **不从 `clause=""` / `DEFINITIONS` 的块回粘**，避免引言和定义区被吸走。
3. **新规则不替换任何现有行为**：引言块首次吸收条款、祖先收短、
   `max_len` 上限判断三条都保持原样；回粘只在它们之前多判一次。

### 锚点

| 文件 | blob hash |
|:---|:---|
| `chunker.py` | `d967d54acda943eb998cacc911a3c650797da323` |
| `tests/test_chunking.py` | `5b62b8e9e744af899a08b4eeb3f322d7359e078b` |
| `README.md` | `f50106981deec6d4f57f5b7bcde32792413ab5d5` |
| `docs/项目技术手册.md` | `6812b39dd9b1a1ee9cc2e982978d7ebf66067b48` |
| `docs/面试话术.md` | `6dabf2ba138863ee6144deb33cedffd9f55dc8c6` |

```bash
git hash-object chunker.py tests/test_chunking.py README.md docs/项目技术手册.md docs/面试话术.md
```

### 验收 gate

| 项 | 内容 |
|:---|:---|
| 命令 | `pytest -q` |
| 判据 1 | 全绿，且不少于基线 83 passed；新增覆盖真续行、句号结束不回粘、跨章不粘 |
| 命令 | `RAG_RERANK=true python run_eval.py` |
| 判据 2 | 10 题 Recall@5 = 10/10，不低于改前 |
| 命令 | `RAG_RERANK=false python run_eval.py` |
| 判据 3 | 10 题 Recall@5 = 9/10，未命中题与改前相同 |
| 命令 | 重切后与备份缓存逐块比对 |
| 判据 4 | 块数 1113 → 1112（恰少 1 块）；正文（`text` 去 `prefix`）按序拼接**逐字节相同** |
| 命令 | 统计 `len(text) > 1200` 的块 |
| 判据 5 | 不引入新的超长块；若回粘块 > 2000 字符则停下来报告 |
| 边界 | 不覆盖向量检索质量相对改前的提升（预期不变），也不覆盖真实部署 |

### 证据

| 文件 | 内容 |
|:---|:---|
| `docs/eval-continuation-rerank.txt` | 10 题，`RAG_RERANK=true`，1112 块，pool=20，Recall@5 = 10/10 |
| `docs/eval-continuation-norerank.txt` | 10 题，`RAG_RERANK=false`，1112 块，Recall@5 = 9/10，未命中「正手高远球最容易犯的错误有哪些？」 |

命令（Windows 下必须指定 UTF-8，否则 emoji 输出触发 `UnicodeEncodeError: 'gbk' codec`）：

```bash
RAG_RERANK=true  PYTHONIOENCODING=utf-8 python run_eval.py > docs/eval-continuation-rerank.txt 2>&1
RAG_RERANK=false PYTHONIOENCODING=utf-8 python run_eval.py > docs/eval-continuation-norerank.txt 2>&1
```

测试：`pytest -q` → `93 passed, 4 skipped, 4 deselected`（基线 83 passed，新增 10 例）。

### 结果

| 指标 | 改前 | 改后 |
|:---|:---|:---|
| 块数 | 1113 | **1112**（-1） |
| 总字符数（含前缀） | 582,108 | **582,092**（-16，少了一份 16 字符前缀） |
| 正文字符数（去前缀） | 561,657 | **561,657**（不变） |
| 正文 sha256 | `1e9b3e8e…90db11f` | **相同** |
| 空 clause 块 | 483 | **482** |
| 块均字数 | 523.0 | **523.5** |
| >1200 字符块 | 39（最长 7,592） | **39（最长 7,592，集合逐块相同）** |

被回粘清单（全库仅 1 处）：

| source | 被吸块页码 | 并入的 clause | 并入块正文长度 | 结果 |
|:---|:---|:---|:---|:---|
| `badminton_rules.pdf` | 3 | `2.3.1`（`prev` 在第 2 页） | 434 字符 | 新第 14 块，page=2，clause=2.3.1，正文 732 字符，含前缀 757 |

逐块比对：旧缓存去掉该孤儿块后，与新缓存 **1112 块一一对应**；
`clause` 序列完全相同，只有第 14 块的正文变化（吸收了第 15 块）。

向量缓存已重算：`(1112, 1024)`，指纹
`38a6e8ce16cdb78a615babad1aa462ad8c83614c92e27266ce5dcf9ea6ebd3d1`。

### 裁决

按 gate 判定通过：pytest 全绿、两口径评测与改前完全一致、块数恰少 1、
正文逐字节相同、没有新增超长块（回粘块 757 字符，远低于 1200）。

**必须记录的偏差**：任务背景里「22 处页首无编号块、16 处应回粘」是对
`data/`（5 份 PDF，含 `itto.pdf`、`vocab.pdf`）跑探针得到的；实际线上语料是
`data_rules_only/`，其中只有 `badminton_rules.pdf` 有分页，其余 15 个来源是
单页 txt，所以真实影响是 **1 处，1113 → 1112**，不是 -16。在 `data/` 上模拟
该规则会得到 16 次回粘、302 → 294 块（净 -8：8 次原本能合并的块在回粘后
超过 1200 而不再合并）。若以后把 itto/vocab PDF 纳入索引，这条规则会按预期
处理那 16 处。

### 遗留

- `data/` 语料未纳入索引；本次只对线上语料验证，itto/vocab 的 15 处续行没有实测。
- 39 个 >1200 字符块是段落回退文档的既有问题（最长 `bwf_ranking.txt` 7,592），
  本轮不动。
- 回粘块页码记句子起点页：第 3 页那半句被引用时会标第 2 页。与既有跨页合并
  的页码策略一致，是已知精度损失。
- 真实部署未执行；向量缓存已在本地重建。

### 回滚

```bash
git revert HEAD          # 本次提交
rm -f chunks_v2.json vectors_v2.npy vectors_v2.meta.json
RAG_DATA_DIR=data_rules_only .venv/Scripts/python.exe index_builder.py
```

回滚后重跑 `pytest -q` 与两种口径 10 题评测，块数应回到 1113、总字符数 582,108。