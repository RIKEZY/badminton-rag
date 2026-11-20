# 2026-11-21 章标题跨页继承

**编号**：2026-11-21-chapter-inherit
**状态**：已采纳
**来源**：P0-1（2026-11-21）遗留的既有缺陷，用户决定单独修

### 范围

| 文件 | 角色 |
|:---|:---|
| `chunker.py` | 被测代码（`split_page_by_clause` / `chunk_document`） |
| `tests/test_chunking.py` | 规格测试（+3 例） |
| `docs/面试话术.md` | 块均字数同步（522 → 523） |

### 改动

`split_page_by_clause` 按页调用，章标题只在章首页出现。翻页后 `chapter_no` /
`chapter_title` 从空开始，块前缀退化成 `[9.1.4.1]`、`[6.6]`，
检索和引用都看不出这块属于哪一章。`badminton_rules.pdf` 有 17 个块受影响，
例如 p6 的 9.1.4.1 / 9.1.7、p7 的 10.2.1 / 10.3.1、p11 的 16.4.1–16.7.1。

改法：

- `split_page_by_clause` 增加可选参数 `chapter_state`（可变字典）：
  进入函数时读取上一页留下的章标题，页末把本页最后的章标题写回；
  本页出现新章标题时覆盖，此后同页块用新章；
- `chunk_document` 每处理**一个文件**新建一份 state，
  不同 source 的章状态不共享，避免上一份文档的章名串到下一份；
- 只改 `chapter` 字段与 `prefix`，不动 `clause` 归属、`merge_siblings` 合并条件、
  `max_len = 1200`。

### 为什么选「直接改 chapter 字段」而不是「仅在加前缀阶段补章」

审查建议里提到两种做法。这里选了在 `split_page_by_clause` 里继承，理由是：

1. `chapter` 是数据本身的属性，不只是显示字段；缓存、评测、以后任何消费方
   都应看到正确的章。若只在 `add_prefix` 补，`chunks_v2.json` 里 chapter 仍是空的，
   下次有人按 chapter 过滤就会再踩一次；
2. 合并判定用的是 `same_chapter = prev["chapter"] == c["chapter"] or not c["chapter"]`。
   旧逻辑对空的 `c["chapter"]` 一律放行，继承后 `c["chapter"]` 等于上一块的章名，
   等值判断同样为真——理论上等价。**实测也等价**：重切后 1113 块逐块比对
   `text`（去前缀）、`clause`、`page`，**0 处差异**；只有 17 个块的 `prefix` 变了。
   所以没有「继承后错误合并」的情况，不需要退到只补前缀的方案。

### 锚点

| 文件 | blob hash |
|:---|:---|
| `chunker.py` | `73b2381096821c841e231199619510dade89369f` |
| `tests/test_chunking.py` | `90cd0c8c49f66dbef909010d8e688c742f3424a9` |

```bash
git hash-object chunker.py tests/test_chunking.py
```

### 验收 gate

| 项 | 内容 |
|:---|:---|
| 命令 | `pytest -q tests/test_chunking.py` |
| 判据 1 | 全部通过；新增 3 例覆盖跨页继承、新章切换、跨 source 不串 |
| 命令 | 重切后逐块比对旧缓存 `chunks_v2.json`（备份） |
| 判据 2 | 块数不变（1113）；`text` 去前缀、`clause`、`page` 全部一致 |
| 命令 | 遍历语料章标题集合，校验每块 `chapter` 是否出现在**本文件**的章标题里 |
| 判据 3 | 0 个跨文件串章 |
| 命令 | `pytest -q` |
| 判据 4 | 全量通过（83 passed） |
| 命令 | `RAG_RERANK=true` / `RAG_RERANK=false` 各跑 10 题 |
| 判据 5 | 10/10 与 9/10，不低于改前 |

### 证据

| 文件 | 内容 |
|:---|:---|
| `docs/eval-chapter-rerank.txt` | 10 题，`RAG_RERANK=true`，Recall@5 = 10/10 |
| `docs/eval-chapter-norerank.txt` | 10 题，`RAG_RERANK=false`，Recall@5 = 9/10，未命中「正手高远球最容易犯的错误」 |

测试：`pytest -q` → `83 passed, 4 skipped, 4 deselected`。

### 结果

| 指标 | 改前 | 改后 |
|:---|:---|:---|
| 块数 | 1113 | **1113**（不变） |
| 字符数 | 581,638 | **582,108**（+470，全部是新增章前缀） |
| 块均字数 | 522 | 523 |
| 无 chapter 块 | 672 | **655** |
| 前缀变化的块 | — | **17**（全部在 `badminton_rules.pdf`） |
| 跨文件串章 | — | **0** |

重切后向量缓存指纹失配，已重算 `(1113, 1024)`，新指纹
`71cd28401728d2ff98ce5251e761f929e7f14b45d3dd45a7348a47fc6e38f145`。

### 裁决

块数不变、正文逐块一致，说明继承只补前缀，没有改变切块边界或合并结果；
两口径评测与改前一致（10/10、9/10，未命中题相同）。

### 遗留

- `bwf_coach_l1.txt` 等段落回退文档走 `split_by_paragraph`，chapter 仍为空
  （42 个章标题未被利用），属另一条线，本轮不动。
- `badminton_rules.pdf` p13 的 `DIAGRAM D` 图例页在 Law 17 之后且无新章标题，
  按「沿用上一章直到新标题」规则被标成 `Law 17. OFFICIALS AND APPEALS`。
  这是规则本身的边界情况：图例并非 Law 17 内容，但也没有可继承的章名。
  若要更准，需要识别 Appendix/Diagram 标记，本轮不做。
- 真实部署未执行；`--with-index` 仍未包含 `vectors_*.meta.json`（沿用上一轮结论）。

### 回滚

```bash
git revert 649ffb7
rm -f chunks_v2.json vectors_v2.npy vectors_v2.meta.json
RAG_DATA_DIR=data_rules_only python index_builder.py
```

回滚后重跑 `pytest -q` 与两种口径 10 题评测，块数应回到 1113、字符数 581,638。